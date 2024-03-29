from __future__ import annotations

import os, sys, glob
sys.path.append(os.path.join(os.getcwd(), 'lisst'))
sys.path.append(os.getcwd())

import time
import numpy as np
import torch
import argparse
import pickle
import json
from typing import Union
from tqdm import tqdm

from torch import optim
from torch.nn import functional as F

from lisst.utils.config_creator import ConfigCreator
from lisst.utils.joint_matching import LISST_TO_MEDIAPOSE
from lisst.models.baseops import (RotConverter, get_scheduler)
from lisst.models.body import LISSTPoser, LISSTCore

from lisst.utils.mv3dpose_joint_matching import LISST_TO_MV3DPOSE

#motion prior
from motion_prior.code.AE_sep import Enc





class LISSTRecOP():
    """operation to perform motion capture from multi-view cameras in ZJUMocap
        
        - the cameras are well calibrated.
        
        - mediapose has been applied applied to perform 2D keypoint estimation.
        
        - only LISST shape and pose priors are used. No advanced motion prior.
    
    """
    
    
    def __init__(self, shapeconfig, poseconfig, testconfig):
        self.dtype = torch.float32
        gpu_index = testconfig['gpu_index']
        if gpu_index >= 0:
            self.device = torch.device('cuda',
                    index=gpu_index) if torch.cuda.is_available() else torch.device('cpu')
        else:
            self.device = torch.device('cpu')
        self.shapeconfig = shapeconfig
        self.poseconfig = poseconfig
        self.testconfig = testconfig

    def build_model(self):
        # load shape model
        self.shaper = LISSTCore(self.shapeconfig)
        self.shaper.eval()
        self.shaper.to(self.device)
        self.nj = self.shaper.num_kpts
        self.shaper.load(self.testconfig['shaper_ckpt_path'])
        
        # load pose model
        self.poser = LISSTPoser(self.poseconfig)
        self.poser.eval()
        self.poser.to(self.device)
        self.poser.load(self.testconfig['poser_ckpt_path'])

        self.weight_sprior = self.testconfig['weight_sprior']
        self.weight_pprior = self.testconfig['weight_pprior']
        self.weight_smoothness = self.testconfig['weight_smoothness']

        self.use_motion_prior = False


    def _cont2rotmat(self, rotcont):
        '''local process from continuous rotation to rotation matrix
        
        Args:
            - rotcont: [t,b,J,6]

        Returns:
            - rotmat: [t,b,J,3,3]
        '''
        nt, nb, nj = rotcont.shape[:-1]
        rotcont = rotcont.contiguous().view(nt*nb*nj, -1)
        rotmat = RotConverter.cont2rotmat(rotcont).view(nt, nb, nj,3,3)
        return rotmat

    def _rotmat2cont(self, rotmat):
        '''local process from rotatiom matrix to continuous rotation
        
        Args:
            - rotmat: [t,b,J,3,3]

        Returns:
            - rotcont: [t,b,J,6]
        '''
        nt,nb,nj = rotmat.shape[:3]
        rotcont = rotmat[:,:,:,:,:-1].contiguous().view(nt,nb,nj,-1)
        return rotcont


    def _add_additional_joints(self, J_rotcont):
        """local implementation of add nose or heels to the model

        Args:
            J_rotcont (torch.Tensor): the poser output without new joints.
        """
        nt, nb = J_rotcont.shape[:2]
        out = self.poser.add_additional_bones(J_rotcont.contiguous().view(nt*nb, -1, 6), 
                        self.shaper.joint_names,
                        self.shaper.get_new_joints())
        
        return out.contiguous().view(nt, nb, -1, 6)


    def fk(self, 
            r_locs: torch.Tensor, 
            J_rotcont: torch.Tensor, 
            bone_length: torch.Tensor, 
            transf_rotcont: Union[None, torch.Tensor]=None,
            transf_transl: Union[None, torch.Tensor]=None) -> torch.Tensor:
        '''forward kinematics.
        The predicted joint locations are discarded and others are preserved for FK.

        Args:
            - r_locs, [t,b,1,3]. The root locations
            - J_rotcont, [t,b,J,6]. The joint rotations
            - bone_length [b,d]. The provided bone length.
            - transf_rotcont, [t,b,1,6]. transfrom from canonical to world
            - transf_transl, [t,b,1,3]. transfrom from canonical to world
        
        Returns:
            - Y_rec_new: [t,b,J,9] The projected bone transform
            - J_locs_fk: [t,b,J,3]. The joint locations via forward kinematics.
        
        '''

        nt, nb = r_locs.shape[:2]
        rotmat = self._cont2rotmat(J_rotcont)
        if transf_rotcont is not None:
            transf_rotmat = self._cont2rotmat(transf_rotcont)
            rotmat = torch.einsum('tbpij,tbpjk->tbpik', transf_rotmat, rotmat)
        if transf_transl is not None:
            r_locs = r_locs + transf_transl
        bone_length = bone_length.unsqueeze(0).repeat(nt, 1,1)
        J_locs_fk = self.shaper.forward_kinematics(r_locs.reshape(nt*nb, 1, 3), 
                                        bone_length.reshape(nt*nb, -1), 
                                        rotmat.reshape(nt*nb, self.nj, 3,3))
        J_locs_fk = J_locs_fk.reshape(nt, nb, self.nj, 3)
        
        
        return J_locs_fk, rotmat




    def img_project(self,
                    J_rec: torch.Tensor, #[t,b,p,3], the last dimension denotes the 3D location
                    cam_rotmat: torch.Tensor, #6D camera rotation w.r.t. origin of the first mp
                    cam_transl: torch.Tensor, # cam translation w.r.t. origin of the first mp,
                    cam_K: torch.Tensor, 
        ):
        # =======================================
        ### TODO!!! Ex.1: implement here
        # Hints:
        # - J_rec is the 3D joint locations in the world coordinate system. 
        # - Based on the camera extrinsics, convert J_rec to J_rec_cam, which has the joint locations in individual camera coordinate systems.
        # - Based on the camera intrinsics, convert J_rec_cam to J_rec_proj, which has the 2D joint locations in the image planes. 
        # - if encountering tensor shape misalignment, you could print these tensor shapes for debugging.
        # - please use our file `data/test_img_project_loss_data.pkl` to test the keypoint detection. 
        #J_rec_proj = None
        # =======================================


        ones = torch.ones(J_rec.size()[0], J_rec.size()[1], J_rec.size()[2],1)
        J_rec = torch.cat([J_rec, ones], dim = -1).transpose(2,3)
        ext_mat = torch.cat([cam_rotmat, cam_transl.transpose(1,2)], dim=-1)
        J_rec_cam = torch.matmul(ext_mat, J_rec)
        J_rec_proj_unorm = torch.matmul(cam_K, J_rec_cam).transpose(2,3)
        J_rec_proj = J_rec_proj_unorm[:,:,:,0:2]/J_rec_proj_unorm[:,:,:,2].unsqueeze(-1)
        
        
        return J_rec_proj




    def generate_img_project_test_file(self, cam_rotmat, cam_transl, cam_K):
        """this function is to test the implementation of `img_project_loss`.
        """
        
        # load data in np
        testdata = np.load('data/test_img_project_loss_data.pkl',allow_pickle=True)
        J_rec = torch.tensor(testdata['J_rec']).float().to(self.device)
        J_rec_proj_gt = torch.tensor(testdata['J_rec_proj']).float().to(self.device)
        J_rec_proj = self.img_project(J_rec, cam_rotmat, cam_transl, cam_K).detach().cpu().numpy()
        np.save('data/test_img_project_loss_data2.npy',J_rec_proj)
        # print('test file saved!')
            
        


    def img_project_loss(self, 
            obs: torch.Tensor, #[t,b,p,3], the last dimension=[x,y,vis]
            J_rec: torch.Tensor, #[t,b,p,3], the last dimension denotes the 3D location
            cam_rotmat: torch.Tensor, #6D camera rotation w.r.t. origin of the first mp
            cam_transl: torch.Tensor, # cam translation w.r.t. origin of the first mp,
            cam_K: torch.Tensor, 
        )->torch.TensorType:
        ''' reprojection loss to multi-view images
        Args:
            - obs: the 2D keypoint detections. [t,b,J,3]. b denotes the camera views. The last dimension = [x,y,vis]
            - J_rec: the 3D joint locations. [t,b=1,J,3]. b=1 if only one person one sequence.
            - cam_rotmat: camera rotation matrix from world to cam. [b,3,3]. b denotes the cam views.
            - cam_transl: camera translation from world to cam. [b,1,3] b denotes the cam views.
            - cam_K: the cam intrinsics. [b,3,3] 
        '''

        # project keypoints and save the file for testing.
        J_rec_proj = self.img_project(J_rec, cam_rotmat, cam_transl, cam_K)
        self.generate_img_project_test_file(cam_rotmat, cam_transl, cam_K)
        
        #calculate the loss
        loss = obs[:,:,:,-1:]*(obs[:,:,:,:-1]-J_rec_proj).abs()
        
        return torch.mean(loss)
    

    def threeD_point_loss(self, poses, J_rec):
        diff = (poses - J_rec).abs()
        loss = diff[diff.isnan() == False].mean()


        #print("number of not nan values: ", (diff.isnan() == False).sum())
        #print("number of nan values: ", diff.isnan().sum())
        return loss
    
    def loss_smoothness(self, J_rec_fk, J_rotcont, mode = 'default'):
        if mode == 'default':
            loc_loss = (J_rec_fk[1:, ...] - J_rec_fk[:-1, ...]).abs().mean()
            rot_loss = (J_rotcont[1:, ...] - J_rotcont[:-1, ...]).abs().mean()

            #print("loc_loss: ", loc_loss, " rot_loss: ", rot_loss)
            loss_smoothness = self.weight_smoothness * (loc_loss + rot_loss)       # + rot_loss

        elif mode == 'allowMove':
            #calculates moving vectors 'vecs' of ech joint location between frames....
            # ...subtracts/compares with movement vectors from timestep before and after and choses the more similar movement(minimum)...
            # ...-> only sudden movements are getting penalized...continues movements are getting penalized less
            
            weight_legs_move = 0       #usally 0
            weight_legs_no_move = 2     #usally 2
            weight_head_move = 1
            weight_head_no_move = 0.2
            weight_back_move = 0.1
            weight_back_no_move = 0
            weight_arms_move = 10
            weight_arms_no_move = 1     #us 0
            less_rot = 0.1
            
            
            vecs = J_rec_fk[1:, ...] - J_rec_fk[:-1, ...]
            diffForward = (vecs[2:, ...] - vecs[1:-1, ...]).abs().mean(dim=-1)
            diffBackward = (vecs[1:-1, ...] - vecs[:-2, ...]).abs().mean(dim=-1)
            diff = torch.minimum(diffForward, diffBackward)
            diff[:,:,[2,3,4,5,7,8,9,10,32,33]] *= weight_legs_move                 #legs + feet
            diff[:,:,[14,15,16,31]] *= weight_head_move                            #head
            diff[:,:,[0,1,6,11,12,13]] *= weight_back_move                         #back + hips + root
            diff[:,:,17:31] *= weight_arms_move                                    #arms + hands   
            loc_loss_move = diff.mean()

            vecs = J_rotcont[1:, ...] - J_rotcont[:-1, ...]
            diffForward = (vecs[2:, ...] - vecs[1:-1, ...]).abs().mean(dim=-1)
            diffBackward = (vecs[1:-1, ...] - vecs[:-2, ...]).abs().mean(dim=-1)
            diff = torch.minimum(diffForward, diffBackward)
            diff[:,:,[2,3,4,5,7,8,9,10,32,33]] *= weight_legs_move                 #legs + feet
            diff[:,:,[14,15,16,31]] *= weight_head_move                            #head
            diff[:,:,[0,1,6,11,12,13]] *= weight_back_move                         #back + hips + root
            diff[:,:,17:31] *= weight_arms_move                                    #arms + hands   
            rot_loss_move = diff.mean()


            diff = J_rec_fk[1:, ...] - J_rec_fk[:-1, ...]
            diff[:,:,[2,3,4,5,7,8,9,10,32,33]] *= weight_legs_no_move                 #legs + feet
            diff[:,:,[14,15,16,31]] *= weight_head_no_move                            #head
            diff[:,:,[0,1,6,11,12,13]] *= weight_back_no_move                         #back + hips + root
            diff[:,:,17:31] *= weight_arms_no_move                                    #arms + hands   
            loc_loss_no_move = diff.abs().mean()

            diff = J_rotcont[1:, ...] - J_rotcont[:-1, ...]
            diff[:,:,[2,3,4,5,7,8,9,10,32,33]] *= weight_legs_no_move                 #legs + feet
            diff[:,:,[14,15,16,31]] *= weight_head_no_move                            #head
            diff[:,:,[0,1,6,11,12,13]] *= weight_back_no_move                         #back + hips + root
            diff[:,:,17:31] *= weight_arms_no_move                                    #arms + hands   
            rot_loss_no_move = diff.abs().mean()


            loss_smoothness = loc_loss_move + less_rot * rot_loss_move + loc_loss_no_move + less_rot * rot_loss_no_move


        return loss_smoothness
    

    def load_motion_prior(self, weight):
        print("load motion prior...")
        self.use_motion_prior = True
        self.encoder = Enc(downsample=False, z_channel=64).to(self.device)
        self.encoder.load_state_dict(torch.load('motion_prior\Enc_last_model.pkl', map_location=self.device))
        self.encoder.eval()
        for param in self.encoder.parameters():
            param.requires_grad = False
        motion_prior_stats = np.load('motion_prior\preprocess_stats_for_our_prior.npz')
        self.motion_prior_Xmean = torch.from_numpy(motion_prior_stats['Xmean'])
        self.motion_prior_Xstd = torch.from_numpy(motion_prior_stats['Xstd'])
        self.motion_prior_weight = weight

        print("...motion prior loaded")


    def motion_prior_loss(self, J_rec_fk, rotmat_rec_fk):
        """"
        J_rec: torch.Tensor, #[t,b,p,3], the last dimension denotes the 3D location
        rotmat_rec_fk should be [t,b,p,3,3]

        """

        # divide tensor in clips of length/time 40, one clip only contains one person, normalize orientation
        clip_len = 40
        variation_of_clip_start = 10
        t = J_rec_fk.shape[0]
        if t > clip_len:
            random_start = np.random.randint(variation_of_clip_start)
            if t - random_start < clip_len:
                random_start = 0
            num_clips = int((t-random_start)/clip_len)
            clip_list = []
            for i in range(num_clips):
                clip_start = random_start + i * clip_len
                clip_end = clip_start + clip_len
                for b in range(J_rec_fk.shape[1]):
                    clip = J_rec_fk[clip_start:clip_end,b,:31,:]                #(40,31,3)
                    transl = clip[0,0,:]                                        #(3)
                    rot = rotmat_rec_fk[clip_start,b,0,:,:]                     #(3,3)

                    clip = clip - transl
                    clip = torch.einsum('ij,...j->...i',rot,clip)
                    clip = clip.reshape(clip.shape[0], -1)                      #(40,93)

                    clip_list.append(clip)
            clip_list = torch.stack(clip_list)                                   #(N,40,93)

            #normalize to standard
            clip_list = (clip_list - self.motion_prior_Xmean) / self.motion_prior_Xstd
            clip_list = clip_list.float().permute(0,2,1).unsqueeze(1)                     #(N,1,93,40) or (N,1,d,T)
            
            #prep for encoder: velocity + padding
            clip_img_v = clip_list[:, :, :, 1:] - clip_list[:, :, :, 0:-1]
            p2d = (8, 8, 1, 1)
            clip_img_v = F.pad(clip_img_v, p2d, 'reflect')
            
            motion_z, _, _, _, _, _ = self.encoder(clip_img_v)

            ####### constraints on latent z
            motion_z_v = motion_z[:, :, :, 1:] - motion_z[:, :, :, 0:-1]
            motion_prior_smooth_loss = torch.mean(motion_z_v ** 2) * self.motion_prior_weight

        else:
            motion_prior_smooth_loss = torch.tensor([0])

        return motion_prior_smooth_loss













    def recover(self,
                posesmv3d: torch.Tensor,
                lr: float = 0.0003,
                n_iter: int = 500,
                to_numpy: bool=True
        ):
        """recover motion primitives based on the body observations.
        We assume the observation (motion, bparams) is a time sequence of smplx bodies
        torch.Tensor and np.ndarray are supported

        Args:
            - motion_obs: the sequence of undistorted 2D pose detections, with the shape [t,b,J,3]. Used as observation
            - cam_rotmat: the camera rotation matrices from world to cam, [b,3,3]. b denoting the views
            - cam_transl: the camera translations from world to cam, [b,1,3]
            - cam_K: the camera intrinsics, [b,3,3]
            - lr: the learning rate of the optimizer (Adam)
            - n_iter: number of iterations for the inner loop
            - to_numpy: produce numpy if true
            
        Returns:
            Y_rec, r_locs, J_rotmat, bone_length, J_locs_3d, J_locs_2d
            
            - Y_rec: the estimated bone transforms [t,J,9], 3D transl + 6D rotcont
            - r_locs: the 3D joint locations [t,1,3], in world coordinate
            - J_rotmat_rec: the rotation matrics [t,J,3,3] in world coordinate
            - bone_length: the bone length [31]
            - J_locs_3d: [t,J,3] in world coordinate
            - J_locs_2d: [t,b,J,2] in the camera view. b denotes the camera view.
        Raises:
            None
        """
        #posesmv3d shape (8,24,3)?
        
        
        #obtain the 2D joint locations corresponding to the openpose/mv3dpose joints.
        traj_idx = []
        poses = []
        for key, val in LISST_TO_MV3DPOSE.items():
            poses.append(posesmv3d[:,:,val].mean(dim=-2, keepdim=True))
        poses = torch.cat(poses, dim=-2)
        #poses = poses.reshape((poses.shape[0], 1) + poses.shape[1:])        #goes from (8,24,3) to (8,1,24,3), prob remove for multiple people
        nt, nb = poses.shape[:2]

        print("posesmv3d shape: ", posesmv3d.shape)
        print("poses shape: ", poses.shape)

    
        #-------setup latent variables to optimize
        #- r_locs: the 3D root translations at all frames about the world coordinate. Note the first joint is the root/pelvis.
        #- J_rotlatent: the joint rotations in the LISSTPoser latent space, about the canonical coordinate.
        #- transf_rotcont: at each frame, we transform the rotation from the canonical frame to the world frame.
        #- betas: the latent variable in the lisst shape space
        nj_cmu = 31
        r_locs = torch.zeros(nt,nb,1,3).float().to(self.device)
        J_rotlatent = torch.zeros(nt*nb, nj_cmu, self.poser.z_dim).to(self.device)         
        transf_rotcont = torch.tensor([1,0,0,1,0,0]).float().repeat(nt,nb,1,1).to(self.device)
        betas = torch.zeros(nb, 12).to(self.device)
        
        r_locs.requires_grad=True 
        J_rotlatent.requires_grad=False
        transf_rotcont.requires_grad=True
        betas.requires_grad=False
        
        optimizer = optim.Adam([r_locs, J_rotlatent, transf_rotcont, betas], lr=lr)
        scheduler = get_scheduler(optimizer, policy='lambda',
                                    num_epochs_fix=0.25*n_iter,
                                    num_epochs=n_iter)

        #--------optimization main loop. 
        ## We set to body pose learnable after several iterations. So our method is in principal stage-wise.
        for jj in range(n_iter):
            # =======================================
            ### TODO!!! Ex.2: implement multistage optimization here
            # Q: Why multistage?
            # A: Inverse kinematics is a highly ill-posed problem. A good initialization is essential.
            # Hints:
            # - In early stages, we only optimize the body global parameters.
            # - In late stages, we optimize both the global and the local body parameters.
            # Multistages can be implemented by enabling/disabling updating certain variables.
            # =======================================

            lateStage = 0
            if jj > 0.1 * n_iter:
                J_rotlatent.requires_grad = True
                betas.requires_grad=True

            if jj > 0.5 * n_iter:
                lateStage = 1
                
        
            
            ss = time.time()
            #yield global motion
            bone_length = self.shaper.decode(betas) #[b,]
            J_rotcont = self.poser.decode(J_rotlatent).contiguous().view(nt, nb, nj_cmu, -1)
            J_rotcont = self._add_additional_joints(J_rotcont)
            J_rec_fk, rotmat_rec_fk = self.fk(r_locs, J_rotcont, bone_length, 
                                        transf_rotcont=transf_rotcont, transf_transl=None)

            #smoothness regularization
            # =======================================
            ### TODO!!! Ex.3: implement a temporal smoothness loss
            # Q: Why temporal smoothness?
            # A: Human motion is smooth. Without this loss, obvious discontinuities are in the result. 
            # Hints:
            # - minimize the l1/l2 norm of the joint location velocity
            # - minimize the l1/l2 norm of the joint rotation velocity
            #loss_smoothness = torch.zeros(1).float().to(self.device)

            loss_smoothness = self.loss_smoothness(J_rec_fk, J_rotcont, mode='allowMove')

            # =======================================
            
            #shape regularization, encouraging to produce mean shape.
            loss_sprior = self.weight_sprior * torch.mean(betas**2)
            
            #pose regularization, encouraging to produce mean pose.
            loss_pprior = self.weight_pprior * torch.mean(J_rotlatent**2)
            

            '''image reprojection loss'''
            # loss_rec = self.img_project_loss(traj, J_rec_fk[:,:,traj_idx], 
            #                          cam_rotmat, cam_transl, cam_K)
            
            loss_rec = self.threeD_point_loss(poses, J_rec_fk)

            if self.use_motion_prior and lateStage:
                loss_motion_prior = self.motion_prior_loss(J_rec_fk, rotmat_rec_fk)
            else:
                loss_motion_prior = torch.tensor([0])
                        
            # print(loss_rec.item())
            loss = loss_rec + lateStage * (loss_smoothness + loss_sprior + loss_pprior + loss_motion_prior)
            '''optimizer'''
            ss = time.time()
            optimizer.zero_grad()
            loss.backward(retain_graph=False)
            optimizer.step()
            if jj % 200==0 or jj==n_iter-1:
                print('[iter_inner={:2d}] PROJ={:.3f}, SPRIOR={:.7f}, PPRIOR={:.7f}, SMOOTH={:.3f}, MotionPr={:.12f}, TIME={:.2f}'.format(
                        jj, loss_rec.item(), loss_sprior.item(), loss_pprior.item(), loss_smoothness.item(), loss_motion_prior.item(),
                        time.time()-ss))
            scheduler.step()
        
        '''output the final results'''
        bone_length = self.shaper.decode(betas) #[b,]
        J_rotcont = self.poser.decode(J_rotlatent)
        J_rotcont = J_rotcont.contiguous().view(nt, nb, nj_cmu, -1) # in canonical frame
        J_rotcont = self._add_additional_joints(J_rotcont)
        J_rec_fk, rotmat_rec_fk = self.fk(r_locs, J_rotcont, bone_length, 
                                    transf_rotcont=transf_rotcont, transf_transl=None)

        #reproject to 2D
        #J_locs_2d = self.img_project(J_rec_fk, cam_rotmat, cam_transl, cam_K)
        # J_rec_cam = torch.einsum('bij,tbpj->tbpi', cam_rotmat, J_rec_fk) + cam_transl.unsqueeze(0)
        

        #change body features to body parameters
        r_locs = J_rec_fk[:,:,:1] # the generated root translation
        J_rotmat = rotmat_rec_fk # the genrated joint rotation matrices

        if to_numpy:
            r_locs = r_locs[:].detach().cpu().numpy() #[t, 1, 3]
            J_rotmat = J_rotmat[:].detach().cpu().numpy() #[ t,J, 3,3]
            bone_length = bone_length[:].detach().cpu().numpy() #[J]
            J_locs_3d = J_rec_fk[:].detach().cpu().numpy() #[t,J,3]
            #J_locs_2d = J_locs_2d.detach().cpu().numpy()
        
        return r_locs, J_rotmat, bone_length, J_locs_3d#, J_locs_2d





    def openpose_to_pickle(self, data_path: str):
        '''
        
        - data_path: the batch generator
        '''
        # output placeholder
        rec_results = {
            'r_locs': None, 
            'J_rotmat': None, 
            'J_shape': None, 
            'J_locs_3d': None 
            #'J_locs_2d': None
        }



        files_in_path = os.listdir(data_path)                                                               #print(files) = ['track0.json', 'track1.json', 'track2.json', 'track3.json', 'track4.json']
        print("files_in_path: ", files_in_path)

        num_of_tracks = len(files_in_path)
        track_summary = []
        start = np.inf
        stop = 0
        for i, file in enumerate(files_in_path):
            with open(os.path.join(data_path, file)) as f:
                data = json.load(f)
            track_summary.append((data["frames"][0], data["frames"][-1]))
            
            start = min(data["frames"][0], start)
            stop = max(data["frames"][-1], stop)

        for i in range(len(track_summary)):
            track_summary[i] = (track_summary[i][0]-start, track_summary[i][1]-start)

        print("track_summary: ", track_summary)
        print("start: ", start, " stop: ", stop)

        #create empty array with shape = (timesteps, number of tracks, Joints, xyz)
        all_poses = torch.full((stop-start+1, num_of_tracks, 30, 3), torch.nan) 
 

        for i, file in enumerate(files_in_path):
            
            with open(os.path.join(data_path, file)) as f:
                data = json.load(f)                                                                         #print(data.keys()) = dict_keys(['J', 'frames', 'poses', 'z_axis'])
            
            #for Null values in data, put nan.... change from cm to meters (not anymore, was before .../100).float ...) ... do torch device stuff like in A3                              
            poses = (torch.tensor([[np.array(sublist) if sublist is not None else np.array([np.nan,np.nan,np.nan]) for sublist in inner_list] for inner_list in data['poses']])/100).float()
            poses = torch.einsum('ij,...j->...i',torch.tensor([[1.,0.,0.],[0,0,1],[0,-1,0]]),poses)    #rotate coordinate system around x
            poses = poses.reshape((poses.shape[0], 1) + poses.shape[1:])

            begin, end = track_summary[i]
            #if there are missing frames
            # if end-begin+1 != len(data['frames']):
            #     print("missing frame in file: ", i)

            #     num_missing = end-begin+1 - len(data['frames'])
            #     poses = torch.full((poses.shape[0]+num_missing,) + poses.shape[1:], torch.nan)
            #     for idx, elem in data['frames']:
            #         if data['frames'][idx-1] != data['frames'][idx]-1:
                        




            all_poses[[frame - start for frame in data['frames']], i:i+1, :, :] = poses            #first entry: begin:end+1
            #fill all timesteps that have no content with first and last pose to not corrupt "important" motion while recovering
            all_poses[:begin, i, :, :] = all_poses[begin, i, :, :]
            all_poses[end+1:, i, :, :] = all_poses[end, i, :, :]


            print("loaded track {} with shape: ".format(i), poses.shape)


        #only works for one person i think...maybe not
        limit_render_length = False
        if limit_render_length:
            all_poses = all_poses[:200, ...]

        
        #old stuff
        # files_in_path = os.listdir(data_path)
        # all_poses_temp = []
        # for i, file in enumerate(files_in_path):
            
        #     with open(os.path.join(data_path, file)) as f:
        #         data = json.load(f)                                                                         #print(data.keys()) = dict_keys(['J', 'frames', 'poses', 'z_axis'])
            
        #     #for Null values in data, put nan.... change from cm to meters (not anymore, was before .../100).float ...) ... do torch device stuff like in A3                              
        #     poses = (torch.tensor([[np.array(sublist) if sublist is not None else np.array([np.nan,np.nan,np.nan]) for sublist in inner_list] for inner_list in data['poses']])/100).float()
        #     poses = torch.einsum('ij,...j->...i',torch.tensor([[1.,0.,0.],[0,0,1],[0,-1,0]]),poses)    #rotate coordinate system around x
        #     poses = poses.reshape((poses.shape[0], 1) + poses.shape[1:])
        #     poses = poses[:150, ...]
        #     all_poses_temp.append(poses)

        #     print("loading track {} with shape: ".format(i), poses.shape)

        
        # all_poses = torch.cat([poses for poses in all_poses_temp], dim=1)

        print("all poses loaded! shape: ", all_poses.shape, " start optimizing...")
              
        # optimization
        ss = time.time()
        results = self.recover(
                            all_poses,
                            lr = self.testconfig['lr'],
                            n_iter = self.testconfig['n_iter'],
                            to_numpy=True
                    )
        
        eps = time.time()-ss
        print('-- takes {:03f} seconds'.format(eps))

        
        #print(results)
        #print("len results: ", len(results))
        #cut off added motion
        if not limit_render_length:
            for i in [0,1,3]:
                print("i: ", i, " results[i] shape: ", results[i].shape)
                for tr in range(num_of_tracks):
                    begin, end = track_summary[tr]
                    results[i][:begin,tr,:] = np.ones(3)*10
                    results[i][end+1:,tr,:] = np.ones(3)*10

       

                    
        for idx, key in enumerate(rec_results.keys()):
            rec_results[key] = results[idx]

        #change to 31 joints format (because 34 joints format doesnt support mutiple people???)
        rec_results['J_rotmat'] = rec_results['J_rotmat'][:,:,:31]
        rec_results['J_locs_3d'] = rec_results['J_locs_3d'][:,:,:31]
        rec_results['J_shape'] = rec_results['J_shape'][:,:31]

        ### save to file
        outfilename = os.path.join(
                            'LISST_output',
                            'output'
                        )
        if not os.path.exists(outfilename):
            os.makedirs(outfilename)
        subjname = os.path.basename(data_path)
        if subjname == '':
            subjname = os.path.basename(data_path[:-1])
        outfilename = os.path.join(outfilename,
                        '{}.pkl'.format(subjname)
                        )
        with open(outfilename, 'wb') as f:
            pickle.dump(rec_results, f)









if __name__ == '__main__':
    """ example command
    python scripts/app_openpose_multiview.py --cfg_shaper=LISST_SHAPER_v2 --cfg_poser=LISST_POSER_v0 --data_path=example_inout/dance
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--cfg_shaper', default=None, required=True)
    parser.add_argument('--cfg_poser', default=None, required=True)
    parser.add_argument('--data_path', default=None, required=True,
                        help="specify the datapath")
    parser.add_argument('--gpu_index', type=int, default=0)
    args = parser.parse_args()

    """setup"""
    np.random.seed(0)
    torch.manual_seed(0)
    torch.set_printoptions(sci_mode=False)
    dtype = torch.float32
    torch.set_default_dtype(dtype)
    
    cfgall_shaper = ConfigCreator(args.cfg_shaper)
    modelcfg_shaper = cfgall_shaper.modelconfig
    losscfg_shaper = cfgall_shaper.lossconfig
    traincfg_shaper = cfgall_shaper.trainconfig
    
    cfgall_poser = ConfigCreator(args.cfg_poser)
    modelcfg_poser = cfgall_poser.modelconfig
    losscfg_poser = cfgall_poser.lossconfig
    traincfg_poser = cfgall_poser.trainconfig
    
    testcfg = {}
    testcfg['gpu_index'] = args.gpu_index
    testcfg['shaper_ckpt_path'] = os.path.join(traincfg_shaper['save_dir'], 'epoch-000.ckp')
    testcfg['poser_ckpt_path'] = os.path.join(traincfg_poser['save_dir'], 'epoch-500.ckp')
    testcfg['result_dir'] = cfgall_shaper.cfg_result_dir
    testcfg['seed'] = 0
    testcfg['lr'] = 0.1
    testcfg['n_iter'] = 2000
    testcfg['weight_sprior'] = 0.0
    testcfg['weight_pprior'] = 0.2           #0.2 for most, 0.05 for dance?
    testcfg['weight_smoothness'] = 0.0       #originally 100, now set in def loss_smoothness
    
    """model and testop"""
    testop = LISSTRecOP(shapeconfig=modelcfg_shaper, poseconfig=modelcfg_poser, testconfig=testcfg)
    # testop.gather_mediapipe_data_for_zju(data_path=args.data_path)
    testop.build_model()
    testop.load_motion_prior(weight = 1000000)
    testop.openpose_to_pickle(data_path=args.data_path) # from test views
    
    


