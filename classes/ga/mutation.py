import os
import numpy as np
from collections import Counter

# More imports at the bottom of module.

class Mutation:
    """
    Carries out mutations operations on a population.

    Instances of the ``Population`` class delegate mating operations to
    instances of this class. They do this by calling:
        
        >>> mutant_pop = pop.gen_mutants()
        
    which returns a new population consisting of molecules generated by
    performing mutation operations on members of ``pop``. This class
    invokes an instance of the ``Selection`` class to select molecules 
    for mutations. Both an instance of this class and the ``Selection``
    class are held in the `ga_tools` attribute of a ``Population`` 
    instance.
    
    This class is initialized with a list of  ``FunctionData`` 
    instances. Each ``FunctionData`` object holds the name of the 
    mutation function to be used by the population as well as any 
    additional parameters the function may require. Mutation functions 
    should be defined as methods within this class. 
    
    A mutation function from the list will be selected at random, with
    likelihoods modified if the user supplies a `weights` list during
    initialization.
    
    Members of this class are also initialized with an integer which
    holds the number of mutation operations to be performed each
    generation.
    
    Attributes
    ----------
    funcs : list of FunctionData instances
        This lists holds all the mutation functions which are to be 
        applied by the GA. One will be chosen at random when a mutation
        is desired. The likelihood can be modified by the optionally 
        supplied `weights` argument.
        
        The ``FunctionData`` object holding the name of the function
        chosen for mutation and any additional paramters and 
        corresponding values the function may require.
    
    num_mutations : int
        The number of mutations that needs to be performed each
        generation.
    
    n_calls : int
        The total number of times an instance of ``Mutation`` has been
        called during its lifetime.
    
    name : str
        A template string for naming ``MacroMolecule`` instances 
        produced during mutation.   
        
    weights : None or list of floats (default = None)
        When ``None`` each mutation function has equal likelihood of
        being picked. If `weights` is a list each float corresponds to
        the probability of selecting the mutation function at the
        corresponding index.
    
    """
    
    def __init__(self, funcs, num_mutations, weights=None):
        self.funcs = funcs
        self.weights = weights
        self.num_mutations = num_mutations
        self.n_calls = 0
        self.name = "mutation_{0}.mol"
    
    def __call__(self, population):
        """
        Carries out mutation operations on the supplied population.
        
        This function selects members of the population to be mutated
        and mutates them. This goes on until either all possible 
        molecules have been mutated or the required number of successful 
        mutation operations have been performed.
        
        The mutants generated are returned together in a ``Population`` 
        instance. Any molecules that are created as a result of mutation 
        that match a molecule present in the original population are 
        removed.

        Parameters
        ----------
        population : Population
            The population who's members are to be mutated.
            
        Returns
        -------
        Population
            A population with all the mutants generated held in the
            `members` attribute. This does not include mutants which
            correspond to molecules already present in `population`.            

        """
        
        parent_pool = population.select('mutation')
        mutant_pop = Population(population.ga_tools)
        counter = Counter()        
        
        num_mutations = 0
        for parent in parent_pool:
            counter.update([parent])
            func_data = np.random.choice(self.funcs, p=self.weights)
            func = getattr(self, func_data.name)            
           
            try:
                self.n_calls += 1
                mutant = func(parent, **func_data.params)
                mutant_pop.members.append(mutant)
                num_mutations += 1
                print('Mutation number {0}. Finish when {1}.'.format(
                                num_mutations, self.num_mutations))

                if num_mutations == self.num_mutations:
                    break

            except Exception as ex:
                MacroMolError(ex, parent, ('Error during mutation'
                    ' with {}.').format(func.__name__)) 

        mutant_pop -= population
        
        # Update counter with unselected members.
        for member in population:
            if member not in counter.keys():
                counter.update({member : 0})
        plot_counter(counter, os.path.join(os.getcwd(), 
                              'mutation_counter.png'))
        return mutant_pop

    def random_bb(self, cage, database):
        """
        Substitutes a building-block* with a random one from a database.
        
        Parameters
        ----------
        cage : Cage
            The cage who's building-block* will be exchanged. Note that
            the cage is not destroyed. It is used a template for a new
            cage.
            
        database : str
            The full path of the database from which a new 
            building-block* is to be found.
            
        Returns
        -------
        Cage
            A cage instance generated by taking all attributes of `cage`
            except its building-block* which is replaced by a random 
            building-block* from `database`.
        
        """
        
        while True:
            bb_file = np.random.choice(os.listdir(database))
            if bb_file.endswith(".mol"):
                break
        bb_file = os.path.join(database, bb_file)
        bb = StructUnit3(bb_file)
        lk = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit2))        
        return Cage((bb, lk), type(cage.topology),
            os.path.join(os.getcwd(), self.name.format(self.n_calls)))

    def random_lk(self, cage, database):
        """
        Substitutes a linker with a random one from a database.
        
        Parameters
        ----------
        cage : Cage
            The cage who's linker will be exchanged. Note that
            the cage is not destroyed. It is used a template for a new
            cage.
            
        database : str
            The full path of the database from which a new linker is to
            be found.
            
        Returns
        -------
        Cage
            A cage instance generated by taking all attributes of `cage`
            except its linker which is replaced by a random linker from
            `database`.
        
        """        

        while True:
            lk_file = np.random.choice(os.listdir(database))
            if lk_file.endswith(".mol"):
                break
        lk_file = os.path.join(database, lk_file)
        lk = StructUnit2(lk_file)
        bb = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit3))        
        return Cage((bb, lk), type(cage.topology),
            os.path.join(os.getcwd(), self.name.format(self.n_calls)))

    def random_cage_topology(self, cage, topologies):
        """
        Changes `cage` topology to a random one from `topologies`.
        
        Parameters
        ----------
        cage : Cage
            The cage which is to be mutated.
        
        topologies : list of CageTopology instances        
            This lists holds the topology classes from which one is 
            selected at random to form a new cage. If the `cage` has
            a topology found in `topologies` that topology will not be
            selected.
            
        Returns
        -------
        Cage
            A cage generated by initializing a new ``Cage`` instance
            with all the same paramters as `cage` except for the
            topology.
        
        """
        
        tops = list(topologies)        
        tops.remove(type(cage.topology))
        topology = np.random.choice(tops)        
        
        return Cage(cage.building_blocks, topology, 
             os.path.join(os.getcwd(), self.name.format(self.n_calls)))

    def similar_bb(self, cage, database):
        """
        Substitute the building-block* with similar one from `database`.
        
        All of the molecules in `database` are checked for similarity to
        the building-block* of `cage`. The first time this mutation
        function is run on a cage, the most similar molecule in
        `database` is used to substitute the building-block*. The next
        time this mutation function is run on the same cage, the second 
        most similar molecule from `database` is used and so on.
        
        Parameters
        ----------
        cage : Cage
            The cage which is to have its building-block* substituted.
            
        database : str
            The full path of the database from which molecules are used
            to substitute the building-block* of `cage`.

        Modifies
        --------
        cage._similar_bb_mols : generator
            Creates this attribute on the `cage` instance. This allows
            the function to keep track of which molecule from `database`
            should be used in the substitution.
            
        Returns
        -------
        Cage
            A new cage with the same linker as `cage` but a different
            building-block*. The building-block* is selected according
            to the description in this docstring.
        
        """
        
        # The first time this function is run it creates a generator
        # which returns molecules from `database`, most similar first.
        # This generator is placed in the `_similar_bb_mols` attribute
        # of `cage`. When this function is run again on the same cage,
        # to get the next molecule from `database` all one needs to do
        # is run ``next()`` on `_similar_bb_mols`. This will return the
        # next most similar molecule in `database`.
        
        if not hasattr(cage, '_similar_bb_mols'):
            bb = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit3))
            cage._similar_bb_mols = bb.similar_molecules(database)
        
        new_bb = StructUnit3(next(cage._similar_bb_mols))
        lk = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit2))
        return Cage((new_bb, lk), type(cage.topology),
              os.path.join(os.getcwd(), self.name.format(self.n_calls)))
        
    def similar_lk(self, cage, database):
        """
        Substitute the linker with a similar one from `database`.
        
        All of the molecules in `database` are checked for similarity to
        the linker of `cage`. The first time this mutation function is 
        run on a cage, the most similar molecule in `database` is used 
        to substitute the linker. The next time this mutation function 
        is run on the same cage, the second most similar molecule from 
        `database` is used and so on.
        
        Parameters
        ----------
        cage : Cage
            The cage which is to have its linker substituted.
            
        database : str
            The full path of the database from which molecules are used
            to substitute the linker of `cage`.

        Modifies
        --------
        cage._similar_lk_mols : generator
            Creates this attribute on the `cage` instance. This allows
            the function to keep track of which molecule from `database`
            should be used in the substitution.
            
        Returns
        -------
        Cage
            A new cage with the same building-block* as `cage` but a 
            different linker. The linker is selected according to the 
            description in this docstring.
        
        """

        # The first time this function is run it creates a generator
        # which returns molecules from `database`, most similar first.
        # This generator is placed in the `_similar_lk_mols` attribute
        # of `cage`. When this function is run again on the same cage,
        # to get the next molecule from `database` all one needs to do
        # is run ``next()`` on `_similar_lk_mols`. This will return the
        # next most similar molecule in `database`.
        
        if not hasattr(cage, '_similar_lk_mols'):
            lk = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit2))
            cage._similar_lk_mols = lk.similar_molecules(database)
        
        new_lk = StructUnit2(next(cage._similar_lk_mols))
        bb = next(x for x in cage.building_blocks if 
                                             isinstance(x, StructUnit3))
        return Cage((new_lk, bb), type(cage.topology),
              os.path.join(os.getcwd(), self.name.format(self.n_calls)))
        
from ..population import Population
from ..molecular import StructUnit3, StructUnit2, Cage, Polymer
from ..exception import MacroMolError
from ...convenience_functions import plot_counter