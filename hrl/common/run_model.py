from pdb import set_trace
import glob
import os

import numpy as np
from stable_baselines.common.vec_env import DummyVecEnv
from stable_baselines import PPO2

from hrl.common.arg_extractor import get_load_args
from hrl.envs import env as environments

def load_model(
        experiment=None,
        folder='experiments', 
        weights=None,
        env='Base',
        full_path=None,
        ):

    if full_path == None:
        if folder[-1] in '\\/':
            # remove \ from the end
            folder = folder[:-1]

        if weights is None:
            # Check what is the last weight
            weights_lst = [s for s in os.listdir('/'.join([folder,experiment])) if "weights_" in s]
            weights_lst = [s.replace('weights_','').replace('.pkl','') for s in weights_lst]
            if 'final' in weights_lst:
                weights = 'weights_final.pkl'
            else:
                weights_lst = [int(s) for s in weights_lst]
                weights = 'weights_' + str(max(weights_lst)) + '.pkl'
        
        weights_loc = '/'.join([folder,experiment,weights])
    else:
        weights_loc = full_path

    # Get env
    env = getattr(environments, env)
    env = DummyVecEnv([env])

    model = PPO2.load(weights_loc)
    model.set_env(env)

    obs = env.reset()
    while True:
        action, _states = model.predict(obs)
        obs, rewards, dones, info = env.step(action)
        env.render()

if __name__ == '__main__':
    # Run arg parser
    args = get_load_args()

    # Run run experiment
    load_model(**args)
