import os, sys, glob
sys.path.append(os.path.join(os.getcwd(), 'lisst'))
sys.path.append(os.getcwd())

import numpy as np
import pytest

def test():
    """load the pseudo gt data"""
    data_pgt = np.load('data/CoreView_313_test.pkl', allow_pickle=True)

    """load the result"""
    data = np.load('results/mocap_zju_a3/data.pkl', allow_pickle=True)

    """compute the metrics"""
    # joint locations
    J_locs_3d_pgt = data_pgt['J_locs_3d']
    J_locs_3d = data['J_locs_3d']
    err_locs_3d = np.mean(np.linalg.norm(J_locs_3d_pgt-J_locs_3d,ord=1,axis=-1))

    if err_locs_3d <=0.001:
        assert False

