#!/usr/bin/env python
"""Provides an implementation of several sequence weighting algorithm"""

from __future__ import division
from random import choice
from numpy.random.mtrand import exponential
from numpy import array, float64 as Float64, dot as matrixmultiply, transpose,\
                ones, zeros
from numpy.linalg import inv as inverse
from cogent.core.profile import Profile
from cogent.core.alignment import Alignment, DenseAlignment
from cogent.parse.tree import DndParser
from cogent.util.array import hamming_distance
from cogent.align.weights.util import Weights, number_of_pseudo_seqs,\
    pseudo_seqs_exact, pseudo_seqs_monte_carlo, row_to_vote, distance_matrix,\
    eigenvector_for_largest_eigenvalue, DNA_ORDER,RNA_ORDER,PROTEIN_ORDER,\
    SeqToProfile
from cogent.core.moltype import BYTES

__author__ = "Sandra Smit"
__copyright__ = "Copyright 2007-2012, The Cogent Project"
__credits__ = ["Sandra Smit", "Rob Knight", "Gavin Huttley"]
__license__ = "GPL"
__version__ = "1.5.2-dev"
__maintainer__ = "Sandra Smit"
__email__ = "sandra.smit@colorado.edu"
__status__ = "Development"

def VA(alignment, distance_method=hamming_distance):
    """Returns Weight object with seq weights according to the VA method.

    alignment: Alignment object
    
    The VA method (Vingron & Argos 1989) calculates the Hamming distance
    between all sequences in the alignment. The weight assigned to a sequence
    is the sum of the distances of all other sequences in the alignment to that
    sequence, divided by the sum of all pairwise distances.

    Example:
            ABBA    ABCA    CBCB
    ABBA    0       1       3   
    ABCA    1       0       2
    CBCB    3       2       1
    ----------------------------
    total   4       3       5   (=12)
    normal. 0.333   0.25    0.417

    so: weight(ABBA) = 0.333, weight(ABCA)=0.25, etc.
    """
    distances = distance_matrix(alignment, distance_method)
    sum_dist = sum(distances)
    #total weights are the normalized sum of distances (sum over each column,
    # divided by the total distance in the matrix
    weights = sum_dist/sum(sum_dist)

    #create a dictionary of {seq_id: weight}
    weight_dict = Weights(dict(zip(alignment.Names,weights)))
    return weight_dict


def VOR(alignment,n=1000,force_monte_carlo=False,mc_threshold=1000):
    """Returns sequence weights according to the Voronoi weighting method.

    alignment: Alignment object
    n: sampling size (in case monte carlo is used)
    force_monte_carlo: generate pseudo seqs with monte carlo always (even
        if there's only a small number of possible unique pseudo seqs
    mc_threshold: threshold of when to use the monte carlo sampling method
        if the number of possible pseudo seqs exceeds this threshold monte
        carlo is used.

    VOR differs from VA in the set of sequences against which it's comparing
    all the sequences in the alignment. In addition to the sequences in the 
    alignment itself, it uses a set of pseudo sequences.
    
    Generating discrete random sequences: 
    A discrete random sequence is generated by choosing with equal
    likelihood at each position one of the residues observed at that position 
    in the alighment. An occurrence of once in the alignment column is 
    sufficient to make the residue type an option. Note: you're choosing 
    with equal likelihood from each of the observed residues (independent 
    of their frequency at that position). In earlier versions of the algorithm 
    the characters were chosen either at the frequency with which they occur 
    at a position or at the frequency with which they occur in the database. 
    Both trials were unsuccesful, because they deviate from random sampling 
    (see Sibbald & Argos 1990).

    Depending on the number of possible pseudo sequences, all of them are 
    used or a random sample is taken (monte carlo).

    Example:
    Alignment: AA, AA, BB
        AA      AA      BB
    AA  0 (.5)  0 (.5)  2
    AB  1 (1/3) 1 (1/3) 1 (1/3)
    BA  1 (1/3) 1 (1/3) 1 (1/3)
    BB  2       2       0 (1)
    -----------------------------
    total 7/6     7/6     10/6
    norm  .291    .291    .418

    For a bigger example with more pseudo sequences, see Henikoff 1994

    I tried the described optimization (pre-calculate the distance to the
    closest sequence). I doesn't have an advantage over the original method.
    """
    
    MC_THRESHOLD = mc_threshold
    
    #decide on sampling method
    if force_monte_carlo or number_of_pseudo_seqs(alignment) > MC_THRESHOLD:
        sampling_method = pseudo_seqs_monte_carlo
    else:
        sampling_method = pseudo_seqs_exact
    #change sequences into arrays
    aln_array = DenseAlignment(alignment, MolType=BYTES)
    weights = zeros(len(aln_array.Names),Float64)
    #calc distances for each pseudo seq
    rows = [array(seq, 'c') for seq in map(str, aln_array.Seqs)]
    for seq in sampling_method(aln_array,n=n):
        seq = array(seq, 'c')
        temp = [hamming_distance(row, seq) for row in rows]
        votes = row_to_vote(array(temp)) #change distances to votes
        weights += votes #add to previous weights
    weight_dict = Weights(dict(zip(aln_array.Names,weights)))
    weight_dict.normalize() #normalize

    return weight_dict


def mVOR(alignment,n=1000,order=DNA_ORDER):
    """Returns sequence weights according to the modified Voronoi method.
    
    alignment: Alignment object
    n: sample size (=number of random profiles to be generated)
    order: specifies the order of the characters found in the alignment,
        used to build the sequence and random profiles.
    
    mVOR is a modification of the VOR method. Instead of generating discrete
    random sequences, it generates random profiles, to sample more equally from
    the sequence space and to prevent random sequences to be equidistant to 
    multiple sequences in the alignment. 

    See the Implementation notes to see how the random profiles are generated
    and compared to the 'sequence profiles' from the alignment.

    Random generalized sequences (or a profile filled with random numbers):
    Sequences that are equidistant to multiple sequences in the alignment
    can form a problem in small datasets. For longer sequences the likelihood
    of this event is negligable. Generating 'random generalized sequences' is 
    a solution, because we're then sampling from continuous sequence space. 
    Each column of a random profile is generated by normalizing a set of 
    independent, exponentially distributed random numbers. In other words, a 
    random profile is a two-dimensional array (rows are chars in the alphabet, 
    columns are positions in the alignment) filled with a random numbers, 
    sampled from the standard exponential distribution (lambda=1, and thus 
    the mean=1), where each column is normalized to one. These random profiles 
    are compared to the special profiles of just one sequence (ones for the 
    single character observed at that position). The distance between the 
    two profiles is simply the Euclidean distance.

    """
    
    weights = zeros(len(alignment.Names),Float64)

    #get seq profiles
    seq_profiles = {}
    for k,v in alignment.items():
        #seq_profiles[k] = ProfileFromSeq(v,order=order)
        seq_profiles[k] = SeqToProfile(v,alphabet=order)

    for count in range(n):
        #generate a random profile
        exp = exponential(1,[alignment.SeqLen,len(order)])
        r = Profile(Data=exp,Alphabet=order)
        r.normalizePositions()
        #append the distance between the random profile and the sequence
        #profile to temp
        temp = [seq_profiles[key].distance(r) for key in alignment.Names]
        votes = row_to_vote(array(temp))
        weights += votes
    weight_dict = Weights(dict(zip(alignment.Names,weights)))
    weight_dict.normalize()
    return weight_dict

def pos_char_weights(alignment, order=DNA_ORDER):
    """Returns the contribution of each character at each position.

    alignment: Alignemnt object
    order: the order of characters in the profile (all observed chars
        in the alignment
    
    This function is used by the function position_based
    
    For example: 
    GYVGS
    GFDGF
    GYDGF
    GYQGG
    
        0       1       2       3       4       5   
    G   1/1*4                           1/1*4   1/3*1
    Y           1/2*3
    F           1/2*1                           1/3*2
    V                   1/3*1
    D                   1/3*2
    Q                   1/3*1
    S                                           1/3*1
    """
    counts = alignment.columnFreqs()
    a = zeros([len(order), alignment.SeqLen],Float64)
    for col, c in enumerate(counts):
        for char in c:
            a[order.index(char),col] = 1/(len(c)*c[char])
    return Profile(a,Alphabet=order)

def PB(alignment, order=DNA_ORDER):
    """Returns sequence weights based on the diversity at each position.

    The position-based (PB) sequence weighting method is described in Henikoff
    1994. The idea is that sequences are weighted by the diversity observed
    at each position in the alignment rather than on the diversity measured
    for whole sequences.

    A simple method to represent the diversity at a position is to award 
    each different residue an equal share of the weight, and then to divide 
    up that weight equally among the sequences sharing the same residue. 
    So if in a position of a MSA, r different residues are represented, 
    a residue represented in only one sequence contributes a score of 1/r to 
    that sequence, whereas a residue represented in s sequences contributes 
    a score of 1/rs to each of the s sequences. For each sequence, the 
    contributions from each position are summed to give a sequences weight.

    See Henikoff 1994 for a good example.
    """
    #calculate the contribution of each character at each position
    pos_weights = pos_char_weights(alignment, order)
    d = pos_weights.Data
    
    result = Weights()

    for key,seq in alignment.items():
        weight = 0
        for idx, char in enumerate(seq):
            weight += d[order.index(char),idx]
            result[key] = weight
    
    result.normalize()
    return result

def SS(alignment):
    """Returns dict of {seq_id: weight} for sequences in the alignment

    alignment: Alignment object

    The SS sequence weighting method is named after Sander and Schneider, 
    who published their method in 1991. 

    Their method starts with the same distance matrix as in the VA method, 
    where distances are the pairwise Hamming distances between the sequences 
    in the alignment. Where the VA method uses the normalized total weights 
    for each sequence, the SS method continues with calculating a 
    self-consistent set of weights.

    They do this by finding the eigenvector of the distance matrix belonging
    to the largest eigenvalue for the matrix. This special eigenvector can 
    be found by a numerical method.
    """

    distances = distance_matrix(alignment)
    v = eigenvector_for_largest_eigenvalue(distances)
    return Weights(dict(zip(alignment.Names,v)))

def ACL(tree):
    """Returns a normalized dictionary of sequence weights {seq_id: weight}

    tree: a PhyloNode object

    The ACL method is named after Altschul, Carroll and Lipman, who published a 
    paper on sequence weighting in 1989.

    The ACL method is based on an idea of Felsenstein (1973). Imagine 
    electrical current flows from the root of the tree down the edges and 
    out the leaves. If the edge lengths are proportional to their electrical 
    resistances, current flowing out each leaf equals the leaf weight.

    The first step in the calculation of the weight vector is calculating a
    variance-covariance matrix. The variance of a leaf is proportional to the 
    distance from the root to that leaf. The covariance of two leaves is 
    proportional to the distance from the root to the last common ancestor 
    of the two leaves.

    The second step in the calculation results in a vector of weights. Suppose
    there are n leaves on the tree. Let i be the vector of size n, all of whose 
    elements are 1.0. The weight vector is calculated as:
    w = (inverse(M)*i)/(transpose(i)*inverse(M)*i)
    See Altschul 1989
    """
    #clip branch lengths to avoid error due to negative or zero branch lengths
    _clip_branch_lengths(tree)
    
    #get a list of sequence IDs (in the order that the tree will be traversed)
    seqs = []
    for n in tree.tips():
        seqs.append(n.Name)

    #initialize the variance-covariance matrix
    m = zeros([len(seqs),len(seqs)],Float64)

    #calculate (co)variances
    #variance of a node is defined as the distance from the root to the leaf
    #covariance of two nodes is defined as the distance from the root to the
    #last common ancestor of the two leaves. 
    for x in tree.tips():
        for y in tree.tips():
            idx_x = seqs.index(x.Name)
            idx_y = seqs.index(y.Name)
            if idx_x == idx_y:
                m[idx_x,idx_y] = x.distance(tree)
            else:
                lca = x.lastCommonAncestor(y)
                dist_lca_root = lca.distance(tree)
                m[idx_x,idx_y] = dist_lca_root
                m[idx_y,idx_x] = dist_lca_root

    #get the inverse of the variance-covariance matrix
    inv = inverse(m)
    #build vector i (vector or ones, length = # of leaves in the tree)
    i = ones(len(seqs),Float64)
    
    numerator = matrixmultiply(inv, i)
    denominator = matrixmultiply(matrixmultiply(transpose(i),inv),i)
    weight_vector = numerator/denominator

    #return a Weights object (is dict {seq_id: weight})
    return Weights(dict(zip(seqs,weight_vector)))


def _clip_branch_lengths(tree, min_val=1e-9, max_val=1e9):
    """Clips branch lengths in tree to a minimum or maximum value

    tree: TreeNode object
    min: minimum value that a branch length should have
    max: maximum value that a branch length should have
    
    Note: tree is changed in place!!!
    """
    for i in tree.traverse():
        bl = i.Length
        if bl > max_val:
            i.Length = max_val
        elif bl < min_val:
            i.Length = min_val

def _set_branch_sum(tree):
    """Sets the branch sum to each node

    tree: TreeNode object

    The branch sum of a node is the total branch length of all the nodes 
    under that node.

    WARNING: changes the tree in place!!!
    """
    total = 0
    for child in tree:
        _set_branch_sum(child)
        total += child.BranchSum
        total += child.Length
    tree.BranchSum = total

def _set_node_weight(tree):
    """Sets the node weight to nodes according to the GSC method.

    tree: TreeNode object
    
    See documentation in GSC on how node weights are calculated.
    
    WARNING: changes the tree in place!!!
    """
    parent = tree.Parent
    if parent is None: #root of tree always has weight of 1.0
        tree.NodeWeight = 1.0
    else:
        tree.NodeWeight = parent.NodeWeight * \
            (tree.Length + tree.BranchSum)/parent.BranchSum
    for child in tree:
        _set_node_weight(child)


def GSC(tree):
    """Returns dict of {seq_id: weight} for each leaf in the tree

    tree: PhyloNode object

    The GSC method is named after Gerstein, Sonnhammer, and Chothia,
    who published their method in 1994.

    The idea is that the sequences are weighted by their total branch length
    in the tree. In the original algorithm weights are calculated from leaves
    to root, we calculate them from the root to the leaves. 

    First, the branch lengths have to be clipped to a minimum and maximum 
    value to avoid errors due to negative or zero branch lengts, and to 
    make sure the method behaves for two identical sequences. Next the 
    branch sum for each node is pre-calulated (the branch sum is the 
    total branch length in the tree below that node). From the (clipped) 
    branch lengths and branch sums, we can now calulate how the weight has 
    to be divided.

    Example:
    tree = (((A:20,B:10)x:30,C:40)r:0);

    weight of the root (r) is always 1
    to the left node (x) goes ((30+30)/100)*1 = 0.6
    to the right node (C) goed (40/100)*1 = 0.4
    to node A goes (20/30)*0.6 = 0.4
    to node B goes (10/30)*0.6 = 0.2
    
    """
    _clip_branch_lengths(tree)
    _set_branch_sum(tree)
    _set_node_weight(tree)
    weights = Weights()
    for n in tree.tips():
        weights[n.Name] = n.NodeWeight
    return weights

#======================================================  
if __name__ == "__main__":

    from old_cogent.base.align import Alignment
    
    #This main block shows the results for four different alignments
    a = Alignment({'seq1':'GYVGS','seq2':'GFDGF','seq3':'GYDGF',\
        'seq4':'GYQGG'},Names=['seq1','seq2','seq3','seq4'])

    b = Alignment({'seq1':'AA', 'seq2':'AA', 'seq3':'BB'},\
        Names=['seq1','seq2','seq3'])

    c = Alignment({'seq1':'AA', 'seq2':'AA', 'seq3':'BB', 'seq4':'BB',\
        'seq5':'CC'},Names=['seq1','seq2','seq3','seq4','seq5'])

    d = Alignment({'seq1':'AGCTA', 'seq2':'AGGTA', 'seq3':'ACCTG',
        'seq4':'TGCAA'},Names=['seq1','seq2','seq3','seq4'])

    print "This is a quick test run of the alignment-based methods"
    
    for al in [a,b,c,d]:
        #determine the needed character order for each alignment
        if al is b or al is c: 
            char_order = "ABC"           
        elif al is a: #need protein_order   
            char_order=PROTEIN_ORDER
        else: #need DNA_order
            char_order=DNA_ORDER

        print "===========ALIGNMENT=============="
        for k in al.Names:
            print '\t'.join([k,al[k]])
        print 'RESULT OF THE VA METHOD:'
        print VA(al)
        print 'RESULT OF THE VOR METHOD:'
        print VOR(al)
        print 'RESULT OF THE mVOR METHOD:'
        print mVOR(al, n=10000, order=char_order)
        print 'RESULTS OF THE SS METHODS:'
        print SS(al)
        print 'RESULTS OF THE PB METHODS:'
        print PB(al, order=char_order)


