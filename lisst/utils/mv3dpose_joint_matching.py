#mv3dpose skips the root (8) from openpose -> 24(mv3dpose) instead of 25(openpose) keypoints
LISST_TO_MV3DPOSE={ 
                'root': [],             #0
                'lhipjoint': [11],
                'lfemur': [12],
                'ltibia':[13],
                'lfoot':[13, 18],       
                'ltoes':[18, 19],       #5
                'rhipjoint':[8],
                'rfemur':[9],
                'rtibia':[10],
                'rfoot':[10, 21],
                'rtoes':[21, 22],       #10
                'lowerback': [],
                'upperback':[],
                'thorax':[],
                'lowerneck':[1],
                'upperneck':[],         #15
                'head':[16, 17],
                'lclavicle':[5],
                'lhumerus':[6],
                'lradius':[],  #same as wrist like in CMU, maybe 6,7 better?
                'lwrist':[7],           #20
                'lhand':[24],#24
                'lfingers':[26],#26
                'lthumb':[25],#25
                'rclavicle':[2],
                'rhumerus':[3],         #25
                'rradius':[],
                'rwrist':[4],
                'rhand':[27],#27
                'rfingers':[29],#29
                'rthumb':[28], #28        #30        
                'nose': [0],
                'lheel':[20],
                'rheel': [23]
        }
