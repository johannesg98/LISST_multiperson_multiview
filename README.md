
# Digital Humans Project: Learning Motion Priors for LISST Multi-Person Capturing

This code is used to recover the 3D tracks from (OpenPose -> mv3dpose -> stitching algorithm). It is based on assignment 3 of the Digital Humans Course of ETH Zürich. An optimizer uses the 3D tracks as well as motion-, pose- and shape-priros and smoothening functions. As an output we get LISST sequences that can be visualized in Blender (Plugin in the "Setup" part).

## Run it

**Motion Prior**

We already provided our motion priors in the folder /motion_prior. You can directly use them.

If you want to further train the motion priors yourself, use [this](https://github.com/johannesg98/LEMO). Add Enc_last_model.pkl and preprocess_stats_for_our_prior.npz to the folder /motion_prior.

**Run**

To run the script, activate the environment by running:
```
..\*name-of-environment*\Scripts\activate
```
Put all tracks in one folder and change the --data_path argument to that folder. The folder should not contain enything else. Then run
```
python scripts/app_openpose_multiview.py --cfg_shaper=LISST_SHAPER_v2 --cfg_poser=LISST_POSER_v0 --data_path=example_input/dance
```
We provided tracks in the example_input folder.

You can find the resulting LISST .pkl file in LISST_output. Visualize it with the Blender plugin by using "Add Animation Batch".





## Setup

**Notice**

- This environment setup is the same as of Assignment 3 of the course [Digital Humans 2023](https://vlg.inf.ethz.ch/teaching/Digital-Humans.html) at ETH Zurich.
- If you already have installed the environment, just add torchvision to your env with running
'''
pip install torchvision
'''
and you can skip the Intallation process.

**Installation**

Same as in assignment 3, we just added torchvision to the requirements.txt:

- Download our pre-trained checkpoints [here](https://drive.google.com/drive/folders/1jcMbJgZtZEHqy-R8e1hjiTkR6V41aX08?usp=sharing). These checkpoints correspond to the model config files.
Please put all the downloaded files to the folder `results/lisst/`.

- CPU-only version is already tested and works.


**First**, create a virtual environment by running
```
python3 -m venv {path_to_venv}
source {path_to_venv}/bin/activate
```

**Second**, install all dependencies by running
```
pip install -r requirements.txt
```
Note that other versions might also work but not are not tested. 
In principle, this codebase is not sensitive to the Pytorch version, so please use the version that fits your own CUDA version and the GPU driver. Note that you may encounter errors like 
```
ERROR: jupyter-packaging 0.12.3 has requirement setuptools>=60.2.0, but you'll have setuptools 44.0.0 which is incompatible.
ERROR: ypy-websocket 0.8.4 has requirement y-py<0.7.0,>=0.6.0, but you'll have y-py 0.5.9 which is incompatible.
```
Ignore them for now.

We further create an extension package [LISST-blender](https://github.com/yz-cnsdqz/LISST-blender) to use our model for character animation and motion re-targeting.










