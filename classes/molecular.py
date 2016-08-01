import numpy as np
from functools import wraps, total_ordering
from operator import attrgetter
import itertools
import weakref
import rdkit
from rdkit import Chem as chem
from rdkit.Chem import AllChem as ac
from collections import namedtuple
from operator import attrgetter
from copy import deepcopy
import os
import math


from ..convenience_functions import dedupe, flatten

class Cached(type):
    """
    A metaclass for creating classes which create cached instances.
    
    """    
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)        
        self.__cache = weakref.WeakValueDictionary()
    
    def __call__(self, *args):
        if args in self.__cache.keys():
            return self.__cache[args]
        else:
            obj = super().__call__(*args)
            self.__cache[args] = obj
            return obj
                               
class FGInfo:
    """
    Contains key information for functional group substitutions.
    
    The point of this class is to register which atom is substituted
    for which, when an atom in a functional group is substituted with a 
    heavy metal atom. If MMEA is to incorporate a new functional group, 
    a new ``FGInfo`` instance should be added to the 
    `functional_group_list` class attribute of ``FGInfo``. 
    
    Adding a new ``FGInfo`` instace to `functional_group_list` will 
    allow the `Topology.join_mols` method to connect this functional 
    group to (all) others during assembly. 
    
    If this new functional group is to connect to another functional 
    group with a double bond during assembly, the symbols of the heavy 
    atoms of both functional groups should be added to the 
    `double_bond_combs` list. The order in which the heavy symbols are 
    placed in the tuple does not matter.
    
    This should be all that is necessary to allow a MMEA to join up a
    new functional group during assembly.    
    
    Class attributes
    ----------------
    functional_groups_list : list of FGInfo instances
        This list holds all ``FGInfo`` instances used by MMEA. If a new
        functional group is to be used by MMEA, a new ``FGInfo`` 
        instance must be added to this list.
        
    double_bond_combs : list of tuples of strings
        When assembly is carried out, if the heavy atoms being joined
        forme a tuple in this list, they will be joined with a double
        rather than single bond. If a single bond is desired there is no
        need to change this variable.

    Attributes
    ----------
    name : str
        The name of the functional group.
    
    smarts : str
        A ``SMARTS`` string describing the functional group.
    
    target_atomic_num : int
        The atomic number of the atom, which is substituted with a heavy 
        atom, in the functional group.
    
    heavy_atomic_num : int
        The atomic number of the heavy atom which replaces the target 
        atom in the functional group.
    
    target_symbol : str
        The atomic symbol of the atom, which is substituted with a heavy 
        atom, in the functional group.        
    
    heavy_symbol : str
        The atomic symbol of the heavy atom which replaces the target 
        atom in the functional group.
    
    delete : set of ints
        When additional atoms need to be removed from the functional
        group atom being substituted, they should be placed in a set
        in this variable. For example, when an aldehyde reacts it loses
        not only the Hydrogen atoms on the central carbon but also the
        oxygen atom. As a result the atomic number of oxygen should be
        placed in a set in this attribute.
        
        If no addtional atoms need to be removed (Hydrogen atoms are
        removed by default) this attribute should be an empty set.
    
    """
    
    __slots__ = ['name', 'smarts_start', 'smarts_end', 'target_atomic_num', 
                 'heavy_atomic_num', 'target_symbol', 'heavy_symbol'] 
    
    def __init__(self, name, smarts_start, smarts_end, target_atomic_num, 
                 heavy_atomic_num, target_symbol, heavy_symbol):
         self.name = name
         self.smarts_start = smarts_start
         self.smarts_end = smarts_end
         self.target_atomic_num = target_atomic_num
         self.heavy_atomic_num = heavy_atomic_num
         self.target_symbol = target_symbol
         self.heavy_symbol = heavy_symbol

FGInfo.functional_group_list = [
                        
    FGInfo("aldehyde", "C(=O)[H]", "[Y]", 6, 39, "C", "Y"), 
    FGInfo("carboxylic acid", "C(=O)O[H]", "[Zr]=O", 6, 40, "C", "Zr"),
    FGInfo("amide", "C(=O)N([H])[H]", "[Nb]=O", 6, 41, "C", "Nb"),
    FGInfo("thioacid", "C(=O)S[H]", "[Mo]=O", 6, 42, "C", "Mo"),
    FGInfo("alcohol", "O[H]", "[Tc]", 8, 43, "O", "Tc"),
    FGInfo("thiol", "[S][H]", "[Ru]", 16, 44, "S", "Ru"),
    FGInfo("amine", "[N]([H])[H]", "[Rh]", 7, 45, "N", "Rh"),       
    FGInfo("nitroso", "N=O","[Pd]", 7, 46, "N", "Pd"),
    FGInfo("boronic acid", "[B](O[H])O[H]", "[Ag]", 5, 47, "B", "Ag")
                             
                             ]

FGInfo.double_bond_combs = [("Rh","Y"), ("Nb","Y"), ("Mb","Rh")]
        
class StructUnit:
    """
    Represents the building blocks of molecules examined by MMEA.
    
    ``Building blocks`` in this case refers to the smallest molecular 
    unit of the assembled molecules (such as cages) examined by MMEA. 
    This is not the be confused with building-blocks* of cages. 
    Building-blocks* of cages are examples of the ``building blocks`` 
    referred to here. To be clear, the ``StructUnit`` class represents 
    all building blocks of the molecules, such as both the linkers and 
    building-blocks* of cages.
    
    To avoid confusion, in the documentation general building blocks 
    represented by ``StructUnit`` are referred to as `building blocks`` 
    while building-blocks* of cages are always referred to as 
    ``building-blocks*``. 
    
    The goal of this class is the conveniently store information about, 
    and perform operations on, single instances of the building blocks 
    used to form the assembled molecules. The class stores information 
    regarding the rdkit instance of the building block, its ``SMILES`` 
    string and the location of its ``.mol`` file. See the attributes 
    section of this docstring for a full list of information stored.
    
    This class also takes care of perfoming substitutions of the 
    functional groups in the building blocks via the 
    `_generate_functional_group_atoms` method. This method is 
    automatically invoked by the initialzer, so each initialized
    instance of ``StructUnit`` should atomatically have all of the 
    attributes associated with the substituted version of the molecular 
    building block.
    
    More information regarding what operations the class supports can be
    found by examining the methods documented below. A noteworthy 
    example is the `shift_heavy_mol` method. This method is invoked
    by other processes in MMEA (such as in the creation of assembled 
    molecules - see the `place_mols` documentation of the ``Topolgy`` 
    class) and is generally very useful. Similar methods such as 
    `set_heavy_mol_position` may be added in the future. Refer to the 
    documentation of `shift_heavy_mol` below for more details. Note that 
    this paragraph is not an exhaustive list of useful operations.
    
    The ``StructUnit`` class is intended to be inherited from. As 
    mentioned before, ``StructUnit`` is a general building block. If one 
    wants to represent a specific building block, such as a linker or 
    building-block* (of a cage) a new class should be created. This new
    class will will inherit ``StructUnit``. In this way, any operations 
    which apply generally to building blocks can be stored here and any
    which apply specifically to one kind of building block such as a 
    linker or building-block* can be placed within its own class.
    
    Consider a useful result of this approach. When setting the 
    coordinates of linkers or building-blocks* during assembly of a 
    cage, it is necessary to know if the molecule you are placing is a 
    building-block* or linker. This is because a building-block* will go 
    on vertex (in this example, this may or may not be generally true)
    and a linker will go on an edge. 
    
    Assume that there is a ``Linker`` and a ``BuildingBlock`` class 
    which inherit from ``StructUnit``. As luck would have it, these 
    classes are in fact implemented in MMEA. Even if nothing is present
    in the class definition itself, both classes will have all the 
    attributes and methods associated with ``StructUnit``. This means
    the positions of the rdkit molecules held in instances of those 
    classes can be shifted with the `shift_heavy_mol` method.
    
    By running:
    
        >>> isinstance(your_struct_unit_instance, Linker)
        
    you can determine if the molecule you are dealing with is an example
    of a building-block* or linker of a cage. As a result you can easily
    choose to run the correct function which shifts the coordinates 
    either to a vertex or an edge.
    
    A final note on the intended use. Each instance of an assembled 
    molecule class (such as an instance of the ``Cage`` class) will have
    one instance of each class derived from ``StructUnit`` at most. It 
    holds information which applies to every building-block* or linker
    present in a class. As a result it does not hold information 
    regarding how individual building-blocks* and linkers are joined
    up in a cage. That is the cage's problem. Specifically cage's 
    `topology` attribute's problem.
    
    In summary, the intended use of this class is to answer questions
    such as (not exhaustive):
        
        > What basic structural units were used in the assembly of this 
          cage?
        > Which functional group was substituted in building-blocks*
          of this cage? 
        > Which atom was substituted for which in the linker? (Note that
          this question is delegated to the ``FGInfo`` instance held in 
          the `func_grp` attribute of a ``StructUnit`` instance)
        > Where is the ``.mol`` file represnting a single 
          building-block* of the cage located?
        > Where is the ``.mol`` file represnting the a single 
          building-block* of the cage, after it has been substituted 
          with a heavy atom, located?
        > Give me an rdkit instance of the molecule which represents the
          building-block* of a cage. Before and after 
          it has been substituted.
        > Give me an rdkit instance of the molecule which represents a
          a single linker of a cage, at postion ``(x,y,z)``.
          
    Questions which this class should not answer include:
    
        > How many building-blocks* does this cage have? (Ask the 
          ``Cage`` instance.)
        > What is the position of a linker within this cage? (Ask the 
          ``Cage`` instance.)
        > Create a bond between this ``Linker`` and ``BuildingBlock``. 
          (Ask the ``Cage`` instance.)
          
    A good guide is to ask ``Can this question be answered by examining
    a single building block molecule in and of itself?``. 
    
    This should be kept in mind when extending MMEA as well. If a 
    functionality which only requires a building block ``in a vaccuum`` 
    is to be added, it should be placed here. If it requires the 
    building blocks relationship to other objects there should be a 
    better place for it (if not, make one). 

    Attributes
    ----------
    prist_mol_file : str
        The full path of the ``.mol`` file (V3000) holding the 
        unsubstituted molecule. This is the only attribute which needs 
        to be provided to the initializer. The remaining attributes have 
        values derived from this ``.mol`` file.
        
    prist_mol : rdkit.Chem.rdchem.Mol
        This is an ``rdkit molecule type``. It is the rdkit instance
        of the molecule held in `prist_mol_file`.
        
    prist_smiles : str
        This string holds the ``SMILES`` code of the unsubstituted form
        of the molecule.
        
    heavy_mol_file : str
        The full path of the ``.mol`` file (V3000) holding the 
        substituted molecule. This attribute is initialized by the 
        initializer indirectly when it calls the `generate_heavy_attrs` 
        method. 
    
    heavy_mol : rdkit.Chem.rdchem.Mol
        The rdkit instance of the substituted molecule. Generated by 
        the initializer when it calls the `generate_heavy_attrs` method.
        
    heavy_smiles : str
        A string holding the ``SMILES`` code of the substituted version
        of the molecule.
    
    func_grp : FGInfo
        This attribute holds an instance of ``FGInfo``. The ``FGInfo``
        instance holds the information regarding which functional group
        was substituted in the pristine molecule and which atom was 
        substituted for which. Furthermore, it also holds the atomic 
        numbers of the atom which was substitued and the one used in its 
        palce. For details on how this information is stored see the 
        ``FGInfo`` class string.
    
    """
    
    def __init__(self, prist_mol_file):
        self.prist_mol_file = prist_mol_file
        self.prist_mol = chem.MolFromMolFile(prist_mol_file, 
                                             sanitize=False, 
                                             removeHs=False)
                                             
        self.prist_smiles = chem.MolToSmiles(self.prist_mol, 
                                             isomericSmiles=True,
                                             allHsExplicit=True)
        
        # Define a generator which yields an ``FGInfo`` instance from
        # the `FGInfo.functional_group_list`. The yielded ``FGInfo``
        # instance represents the functional group found on the pristine
        # molecule used for initialization. The generator determines 
        # the functional group of the molecule from the path of its 
        # ``.mol`` file. 
        
        # The database of precursors should be organized such that any 
        # given ``.mol`` file has the name of its functional group in
        # its path. Ideally, this will happen because the ``.mol`` file
        # is in a folder named after the functional group the molecule 
        # in the ``.mol`` file contains. This means each ``.mol`` file 
        # should have the name of only one functional group in its path. 
        # If this is not the case, the generator will return the 
        # functional group which appears first in 
        # `FGInfo.functional_group_list`.
        
        # Calling the ``next`` function on this generator causes it to
        # yield the first (and what should be the only) result. The
        # generator will return ``None`` if it does not find the name of
        # a functional group in the path of the ``.mol`` file.
        self.func_grp = next((x for x in 
                                FGInfo.functional_group_list if 
                                x.name in prist_mol_file), None)
        
        # Calling this function generates all the attributes assciated
        # with the molecule the functional group has been subtituted
        # with heavy atoms.
        self._generate_heavy_attrs()

    def _generate_heavy_attrs(self):
        """
        Adds attributes associated with a substituted functional group.
        
        This function is private because it should not be used outside 
        of the initializer.
        
        In essence, this function first finds all atoms in the molecule 
        which form a functional group. It then switches the atoms in the 
        functional groups of the molecule for heavy atoms. This new
        molecule is then stored in the ``StructUnit`` instance in the 
        form of an ``rdkit.Chem.rdchem.Mol``, a SMILES string and a 
        ``.mol`` file path.

        Modifies
        --------
        self : StructUnit
            Adds the `heavy_mol`, `heavy_mol_file` and `heavy_smiles`
            attributes to ``self``.
        
        Returns
        -------
        None : NoneType                

        """
        
        # First create a copy of the ``rdkit.Chem.rdchem.Mol`` instance
        # representing the pristine molecule. This is so that after 
        # any changes are made, the pristine molecule's data is not 
        # corrupted. This second copy which will turn into the 
        # substituted ``rdkit.Chem.rdchem.Mol`` will be operated on.
        self.heavy_mol = deepcopy(self.prist_mol)      
        
        # Subtitutes the relevent functional group atoms in `heavy_mol`
        # for heavy atoms.        
        self._make_atoms_heavy_in_heavy()
        
        
        # Change the pristine ``.mol`` file name to include the word
        # ``HEAVY_`` at the end. This generates the name of the 
        # substituted version of the ``.mol`` file.
        heavy_file_name = list(os.path.splitext(self.prist_mol_file))
        heavy_file_name.insert(1,'HEAVY')
        heavy_file_name.insert(2, self.func_grp.name)
        self.heavy_mol_file = '_'.join(heavy_file_name)     
        
        chem.MolToMolFile(self.heavy_mol, self.heavy_mol_file,
                          includeStereo=False, kekulize=False,
                          forceV3000=True) 

        self.heavy_smiles = chem.MolToSmiles(self.heavy_mol, 
                                             isomericSmiles=True,
                                             allHsExplicit=True)        

    def find_functional_group_atoms(self):
        """
        Returns a container of atom ids of atoms in functional groups.

        The ``StructUnit`` instance (`self`) represents a molecule. 
        This molecule is in turn represented in rdkit by a 
        ``rdkit.Chem.rdchem.Mol`` instance. This rdkit molecule instance 
        is held by `self` in the `prist_mol` attribute. In rdkit the
        molecule instance is made up of constitutent atoms which are
        ``rdkit.Chem.rdchem.Atom`` instances. Within an rdkit molecule,
        each such atom instance has its own id. These are the ids
        contained in the tuple returned by this function. Simple right?   

        Returns
        -------
        tuple of tuples of ints
            The form of the returned tuple is:
            ((1,2,3), (4,5,6), (7,8,9)). This means that all atoms with
            ids 1 to 9 are in a functional group and that the atoms 1, 2
            and 3 all form one functional group together. So do 4, 5 and 
            5 and so on.

        """
        
        # Generate a ``rdkit.Chem.rdchem.Mol`` instance which represents
        # the functional group of the molecule.        
        func_grp_mol = chem.MolFromSmarts(self.func_grp.smarts_start)
        
        # Do a substructure search on the the molecule in `prist_mol`
        # to find which atoms match the functional group. Return the
        # atom ids of those atoms.
        return self.prist_mol.GetSubstructMatches(func_grp_mol)        

    def shift_heavy_mol(self, x, y, z):
        """
        Shifts the coordinates of all atoms in `heavy_mol`.
        
        The `heavy_mol` attribute holds a ``rdkit.Chem.rdchem.Mol``
        instance. This instance holds holds a 
        ``rdkit.Chem.rdchem.Conformer`` instance. The conformer instance
        holds the positions of the atoms within that conformer. This
        function creates a new conformer with all the coordinates
        shifted by `x`, `y` and `z` as appropriate. This function does
        not change the existing conformer.
        
        To be clear, consider the following code:
        
            >>> b = a.shift_heavy_mol(10,10,10)
            >>> c = a.shift_heavy_mol(10,10,10)
        
        In the preceeding code where ``a`` is a ``StructUnit`` instance, 
        ``b`` and ``c`` are two new ``rdkit.Chem.rdchem.Mol`` instances. 
        The ``rdkit.Chem.rdchem.Mol`` instances held by ``a`` in 
        `prist_mol` and `heavy_mol` are completely unchanged. As are any 
        other attributes of ``a``. Both ``b`` and ``c`` are rdkit 
        molecule instances with conformers which are exactly the same.
        Both of these conformers are exactly like the conformer of the 
        heavy rdkit molecule in ``a`` except all the atomic positions
        are increased by 10 in the x, y and z directions. 
        
        Because a was not modified by runnig the method, running it
        with the same arguments leads to the same result. This is why
        the conformers in ``b`` and ``c`` are the same.

        Returns
        -------
        rdkit.Chem.rdchem.Mol
            An rdkit molecule instance which has a modified version of 
            the conformer found in `heavy_mol. Note that the conformer 
            instance is stored by this attribute indirectly. The 
            modification is that all atoms in the conformer are shifted 
            by amount given in the `x`, `y` and `z` arguments.
        
        """
        
        # The function does not modify the existing conformer, as a 
        # result a new instance is created and used for modification.
        conformer = chem.Conformer(self.heavy_mol.GetConformer())
        
        # For each atom, get the atomic positions from the conformer 
        # and add `x`, `y` and `z` to them, as appropriate. This induces 
        # the shift. Create a new geometry instance from these new
        # coordinate values. The geometry instance is used by rdkit to
        # store the coordinates of atoms. Finally, set the conformers
        # atomic position to the values stored in this newly generated
        # geometry instance.
        for atom in self.heavy_mol.GetAtoms():
            
            # Remember the id of the atom you are currently using. It 
            # is used to change the position of the correct atom at the
            # end of the loop.
            atom_id = atom.GetIdx()
            
            # `atom_position` in an instance holding in the x, y and z 
            # coordinates of an atom in its 'x', 'y' and 'z' attributes.
            atom_position = conformer.GetAtomPosition(atom_id)
            
            # Inducing the shift.
            new_x = atom_position.x + x
            new_y = atom_position.y + y
            new_z = atom_position.z + z
            
            # Creating a new geometry instance.
            new_coords = rdkit.Geometry.rdGeometry.Point3D(new_x, 
                                                           new_y, new_z)            
            
            # Changes the position of the atom in the conformer to the
            # values stored in the new geometry instance.
            conformer.SetAtomPosition(atom_id, new_coords)
        
        # Create a new copy of the rdkit molecule instance representing
        # the substituted molecule - the original instance is not to be
        # modified.
        new_heavy = deepcopy(self.heavy_mol)
        
        # The new rdkit molecule was copied from the one held in the
        # `heavy_mol` attribute, as result it has a copy of its
        # conformer. To prevent the rdkit molecule from holding multiple
        # conformers the `RemoveAllConformers` method is run first. The
        # shifted confer is then given to the rdkit molecule, which is
        # returned.
        new_heavy.RemoveAllConformers()
        new_heavy.AddConformer(conformer)
        return new_heavy        
        
    def get_heavy_coords(self):
        """
        Yields the x, y and z coordinates of atoms in `heavy_mol`.        

        The `heavy_mol` attribute holds a ``rdkit.Chem.rdchem.Mol``
        instance. This instance holds holds a 
        ``rdkit.Chem.rdchem.Conformer`` instance. The conformer instance
        holds the positions of the atoms within that conformer. This
        generator yields those coordinates.
        
        Yields
        ------
        tuple of ints
            The tuple itself represents the complete position in space.
            Each int represents the value of the x, y or z coordinate of 
            an atom. The x, y and z coordinates are located in the tuple
            in that order. 
        
        """
        # Get the conformer from the instance in the `heavy_mol` 
        # attribute. 
        conformer = self.heavy_mol.GetConformer()
        
        # Go through all the atoms and ask the conformer to return
        # the position of each atom. This is done by supplying the 
        # conformers `GetAtomPosition` method with the atom's id.
        for atom in self.heavy_mol.GetAtoms():        
            atom_position = conformer.GetAtomPosition(atom.GetIdx())
            yield atom_position.x, atom_position.y, atom_position.z
  
    def _make_atoms_heavy_in_heavy(self):
        """

        """        
        
        func_grp_mol = chem.MolFromSmarts(self.func_grp.smarts_start)
        func_grp_mol_end = chem.MolFromSmarts(self.func_grp.smarts_end)
        rms = ac.ReplaceSubstructs(self.prist_mol, func_grp_mol, func_grp_mol_end, replaceAll=True)
        self.heavy_mol = rms[0]
                
class BuildingBlock(StructUnit):
    """
    Holds information about the building-blocks* of a cage.
    
    """
    
    pass
        
class Linker(StructUnit):
    """
    Holds information about the linkers of a cage.
    
    """
    
    pass

@total_ordering
class Cage(metaclass=Cached):
    """
    A class for MMEA individuals which are porous molecular cages.
    
    The goal of this class is to represent an individual used by a GA.
    As such, it holds attributes that are to be expected for this 
    purpose. Mainly, it has a fitness value stored in its `fitness` 
    attribute and a genetic code - as defined by its `bb`, `lk` and 
    `topology` attributes. Changing any one of these three attributes 
    will result in a different cage, while providing the same attributes
    again should yield the same cage.
    
    Because of this, as well as the computational cost associated with
    cage creation, instances of this class are cached. This means that
    providing the same arguments to the initializer will not build a 
    different instance with the same attribute values. It will yield the 
    original instance, retrieved from memory.
    
    To prevent unecessary bulk to this class any information that can
    be categoraized is. For example, a cage has a building-block* and a
    linker. Both of these structural units have information associated
    with them. These are things like ``SMILES`` strings, ``.mol`` files
    and more. All of these things are held within the instances held by
    the `bb` and `lk` attributes. Equally, anything to do with topolgy 
    should be held by a ``Topology`` instance in the topology attribute.
    
    If new inormation associated with cages is to be added at some point
    in the future, and that information can be grouped together in a
    logical category, a new class should be created to store and 
    manipulate this data. It should not be given to the cage directly.
    Alternatively if more information to do with one of the already 
    present categories, it should be added there.
    
    However information dealing with the cage as a whole can be added
    directly to attributes. You can see examples of such attributes 
    alone. Topology is an exception to this because, despite applying to 
    the cage as a whole, it a complex aspect with its own functions and 
    data. Simple identifiers such as ``.mol`` files and ``SMILES`` 
    strings do not benefit from being grouped together. (Unless they
    pertain to specific substructures within the cages such as linkers
    and building-blocks* - as mentioned before.)
    
    This class also supports comparison operations, these act on the 
    fitness value assiciated with a cage. Comparison operations not 
    explicitly defined are included via the ``total_ordering`` 
    decorator. For other operations and methods supported by this class 
    examine the rest of the class definition.

    Finally, a word of caution. The equality operator ``==`` compares 
    fitness values. This means two cages, made from different building 
    blocks, can compare equal if they happen to have the same fitness. 
    The operator is not to be used to check if one cage is the same 
    structurally as another. To do this check use the `same_cage` 
    method. In addition the ``is`` operator is implemented as is default
    in Python. It compares whether two objects are in the same location 
    in memory. Because the ``Cage`` class is cached the ``is`` operator
    could in principle be used instead of the `same_cage` method. 
    However, this is not intended use and not guarnteed to work in 
    future implementations. If caching stops being implemented such code 
    would break.

    Attributes
    ----------
    bb : BuildingBlock
        This attribute represents a single building-block* molecule and
        holds information pertaining to that function.
    
    lk : Linker
        This attribute represents a single linker molecule and holds 
        information pertaining to that function.

    topology : A child class of ``Topology``
        Represents the topology of the cage. Any information to do with
        how individual building blocks of the cage are organized and
        joined up in space is held by this attribute. For more details
        about what information and functions this entails see  the 
        docstring of the ``Topology`` class and its derived classes.

    prist_mol_file : str
        The full path of the ``.mol`` file holding the pristine version
        of the cage molecule.

    prist_mol : rdkit.Chem.rdchem.Mol
        An rdkit molecule instance representing the cage molecule.

    prist_smiles : str
        A ``SMILES`` string which represents the pristine cage molecule.
        
    heavy_mol_file : str
        The full path of the ``.mol`` file holding the substituted
        version of the cage molecule.

    heavy_mol : rdkit.Chem.rdchem.Mol
        A rdkit molecule instance holding the substituted version of the
        cage molecule.

    heavy_smiles : str
        A ``SMILES`` string representing the substitued version of the 
        cage molecule.

    fitness : float
        The fitness value of the cage, as determined by the chosen
        fitness function.         
    
    """
    
    def __init__(self, *args):
        """
        Initializes ``Cage`` instances.
        
        Several different initializers for this class are available.
        Which one is chosen depends on the number of arguments provided
        to the initializer. When 3 arguments are provided the
        initializer used for testing is used. When the 4 arguments are
        provided the standarnd initializer used when running MMEA is 
        used. For details on what the parameters passed should be check
        documentation of the individual initializers.
        
        """
        
        if len(args) == 3:
            self.testing_init(*args)
        if len(args) == 4:
            self.std_init(*args)
        
        # A numerical fitness is assigned by fitness functions evoked
        # by a ``Population`` instance's `GATools` attribute.
        self.fitness = None

    def std_init(self, bb_file, lk_file, topology, prist_mol_file):
        """
        Initialize a ``Cage`` instance used during MMEA runtime.
        
        Parameters
        ---------
        bb_file : str
            The full path of the ``.mol`` file storing the pristine
            molecule to be used a building-block*.
            
        lk_file : str
            The full path of the ``.mol`` file storing the pristine
            molecule to be used a linker.
            
        topology : A child class of ``Topology``
            The class which defines the topology of the cage. Such 
            classes are defined in the topology module. The class will
            be a child class which inherits the base class ``Topology``.
            
        prist_mol_file : str
            The full path of the ``.mol`` file where the cage molecule
            will be stored.
            
        """
        
        self.bb = BuildingBlock(bb_file)
        self.lk = Linker(lk_file)

        # A ``Topology`` subclass instance must be initiazlied with a 
        # copy of the cage it is describing.        
        self.topology = topology(self)
        self.prist_mol_file = prist_mol_file
        
        # This generates the name of the heavy ``.mol`` file by adding
        # ``HEAVY_`` at the end of the pristine's ``.mol`` file's name. 
        heavy_mol_file = list(os.path.splitext(prist_mol_file))
        heavy_mol_file.insert(1,'HEAVY')        
        self.heavy_mol_file = '_'.join(heavy_mol_file) 
        
        # Ask the ``Topology`` instance to assemble/build the cage. This
        # creates the cage's ``.mol`` file all  the building blocks and
        # linkers joined up. Both the substituted and pristine versions.
        self.topology.build_cage()
        
        # Use the assembled cage in the ``.mol`` files to generate
        # rdkit instances of the pristine and substituted cages and
        # their ``SMILES`` strings.
        self.prist_mol = chem.MolFromMolFile(self.prist_mol_file,
                                             sanitize=False, 
                                             removeHs=False)
                                             
        # Add Hydrogens to the pristine version of the molecule and
        # ensure this updated molecule is added to the ``.mol`` file as 
        # well. The ``GetSSSR`` function and optimization ensure that 
        self.prist_mol = chem.AddHs(self.prist_mol)
        chem.GetSSSR(self.prist_mol)
        ac.MMFFOptimizeMolecule(self.prist_mol)  
        
        chem.MolToMolFile(self.prist_mol, self.prist_mol_file,
                          includeStereo=False, kekulize=False,
                          forceV3000=True)                                             
                                             
        self.heavy_mol = chem.MolFromMolFile(self.heavy_mol_file,
                                             sanitize=False, 
                                             removeHs=False)
        
        self.prist_smiles = chem.MolToSmiles(self.prist_mol, 
                                             isomericSmiles=True, 
                                             allHsExplicit=True)                                               
        self.heavy_smiles = chem.MolToSmiles(self.heavy_mol,
                                             isomericSmiles=True,
                                             allHsExplicit=True) 
                                             
    def same_cage(self, other):
        """
        Check if the `other` instance describes the same cage structure.
        
        Parameters
        ----------
        other : Cage
            The ``Cage`` instance you are checking has the same 
            structure.
        
        Returns
        -------
        bool
            Returns ``True`` if the building-block*, linker and 
            topology of the cages are all the same.
        
        """
        # Compare the building blocks and topology making up the cage.
        # If these are the same then the cages have the same structure.
        return (self.bb == other.bb and self.lk == other.lk and 
                                    self.topology == other.topology)
    
    def __eq__(self, other):
        return self.fitness == other.fitness
        
    def __lt__(self, other):
        return self.fitness < other.fitness
    
    def __str__(self):
        return str(self.__dict__) + "\n"
    
    def __repr__(self):
        return str(self.__dict__) + "\n"
        
    def __hash__(self):
        return id(self)

    """
    The following methods are inteded for convenience while 
    debugging or testing and should not be used during typical 
    execution of the program.
    
    """

    def testing_init(self, bb_str, lk_str, topology_str):
        self.bb = bb_str
        self.lk = lk_str
        self.topology = topology_str

    @classmethod
    def init_empty(cls):
        obj = cls()
        string = ['a','b','c','d','e','f','g','h','i','j','k','l','m',
                  'n','o', 'p','q','r','s','t','u','v','w','x','y','z']
        obj.bb = np.random.choice(string)
        obj.lk = np.random.choice(string)
        obj.fitness = abs(np.random.sample())
        return obj



        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        