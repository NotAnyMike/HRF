import os
import shutil
import psutil
import sys
from pdb import set_trace
from copy import deepcopy,copy

import pandas as pd
import numpy as np
import tqdm
from tensorboard_logger import Logger
from stable_baselines.common.policies import CnnPolicy
from stable_baselines.common.vec_env import SubprocVecEnv
from stable_baselines import PPO2
from pynput.keyboard import Key, Listener, KeyCode

from hrl.common.arg_extractor import get_train_args
from hrl.envs import env as environments

def run_experiment(
        not_save=False, 
        folder='experiments', 
        weights_location=None,
        tag=None,
        env='Base',
        env_num=4,
        n=0,
        save_interval=10000,
        train_steps=int(1e6),
        description=None,
        weights=None,
        n_steps=200,
        ):
    
    if weights is not None and not os.path.isfile(weights):
        raise ValueError("Weights do not exist")

    # Saving args
    args = deepcopy(locals())

    # Get env
    env = getattr(environments, env)
    env = SubprocVecEnv([lambda : env() for i in range(env_num)])

    args['env_config'] = str(env.env_method("get_org_config")[0])

    if os.path.exists(folder + '/to_delete'):
        shutil.rmtree(folder + '/to_delete')
    
    # Check if folder exists and is a valid name
    if not not_save:
        folder = folder.replace(' ', '_')
        if os.path.exists(folder):
            print(" - Folder for experiments found")
        else:
            print(" - Creating folder for experiments")
            os.makedirs(folder)

        # Load cvs of experiments
        experiment_csv = '/'.join([folder, "experiments.csv"])
        print(os.getcwd())
        if os.path.isfile(experiment_csv):
            print(" - Loading experiments.csv file")
            df = pd.read_csv(experiment_csv, index_col=0)
        else:
            print(" - experiments.csv not found, creating one")
            df = pd.DataFrame(columns=args.keys())
            df.to_csv(experiment_csv)

        df = df.append(args, ignore_index=True)
        df.to_csv(experiment_csv)
        id = df.index[-1]

        # Creating folder for experiment
        if tag is None: 
            experiment_folder = '/'.join([folder,str(df.index[-1])])
        else: 
            experiment_folder = '/'.join([folder,str(df.index[-1])+'_'+tag])
        os.makedirs(experiment_folder)

        logs_folder = experiment_folder + '/logs'
        logger = Logger(logs_folder+"/extra")

        del df
    else:
        id = -1
        logs_folder= None
        logger = None
        experiment_folder = None

    if weights is not None:
        model = PPO2.load(
                weights,
                verbose=0,
                tensorboard_log=logs_folder,
                max_grad_norm=100,
                n_steps=n_steps,
                #policy_kwargs={'data_format':'NCHW'},
                )
        model.set_env(env)
    else:
        model = PPO2(
                    CnnPolicy, 
                    env,
                    verbose=0,
                    tensorboard_log=logs_folder,
                    max_grad_norm=100,
                    n_steps=n_steps,
                    #policy_kwargs={'data_format':'NCHW'},
                )

    # set bar
    callback = Callback(
            not_save=not_save,
            logger=logger,
            train_steps=train_steps,
            n=n,
            experiment_folder=experiment_folder,
            save_interval=save_interval,
            id=id,
            )

    # Start running experiment
    # Creating nice table
    _width = 40
    del args['env_config']
    max_k_width = max([len(k) for k in args])
    print("\n{}".format("#"*_width))
    print("# {1:^{0}} #".format(_width-4, "RUNNING EXPERIMENT"))
    print("# {1:^{0}} #".format(_width-4, ""))
    print("# {1:<{0}} #".format(_width-4, "{0:{2}s}: {1:03d}".format("ID",id,max_k_width)))
    for k,v in args.items():
        if type(v) in [float,int]:
            print("# {1:<{0}} #".format(_width-4,"{0:{2}s}: {1:0d}".format(k,v,max_k_width)))
        else:
            print("# {1:<{0}} #".format(_width-4,"{0:{2}s}: {1:s}".format(k,str(v),max_k_width)))
    print("{}".format("#"*_width))
    del args

    print("\n############ STARTING TRAINING ###########\n")
    try:
        with tqdm.tqdm(total=train_steps, leave=True) as bar:
            callback.set_bars(bar)
            model.learn(
                    total_timesteps=train_steps,
                    callback=callback,
                    )

        if not not_save:
            model.save(experiment_folder+"/weights_final")

    except KeyboardInterrupt:
        if not not_save and input("Do you want to DELETE this experiment? (Yes/n) ") == "Yes":
            df = pd.read_csv(experiment_csv, index_col=0)
            df.drop(df.index[id],inplace=True)
            df.to_csv(experiment_csv)

            os.rename(experiment_folder, folder + '/to_delete/')
        else:
            if not not_save:
                model.save(experiment_folder+"/weights_final")

class Callback:
    def __init__(self,not_save,logger,train_steps,n,experiment_folder,
            save_interval, id):

        self.last_step = 0
        self.last_step_saved = 0

        self.not_save = not_save
        self.logger = logger
        self.n = n
        self.train_steps = train_steps
        self.experiment_folder = experiment_folder
        self.save_interval = save_interval 
        self.id = id

    def set_bars(self, global_bar):
        self.global_bar = global_bar

    def _get_stats(self):
        pid = os.getpid()
        process = psutil.Process(pid)

        with process.oneshot():
            mem = process.memory_info()[0]

        for child in process.children():
            with child.oneshot():
                mem += child.memory_info()[0]

        mem /= (2**30)
        
        return mem

    def __call__(self, local_vars, global_vars):
        current_step = int(self.n + local_vars['self'].num_timesteps)
        self.global_bar.update(current_step - self.last_step)

        # TODO Print the name of experiment
        self.global_bar.set_description("Training | ID: %i | fps: %i" \
                % (self.id,int(local_vars['fps'])))

        if self.save_interval > 0 and not self.not_save:
            if current_step - self.last_step_saved > self.save_interval:
                self.last_step_saved = current_step
                local_vars['self'].save(self.experiment_folder + '/weights_'+str(current_step))

            mem = self._get_stats()

            # Log actions taken
            self.logger.log_histogram('episode/actions', local_vars['actions'], current_step)
            self.logger.log_value("resources/ram",mem, current_step)

            # Reward also because the normal logger does not log every episode
            #self.logger.log_value('episode/ep_reward', local_vars['true_reward'], current_step)

            # Log num steps
            #self.logger.log_value('episode/ep_steps', local_vars['steps'], current_step)

        self.last_step = current_step
        if current_step >= local_vars['total_timesteps']: return False

if __name__ == '__main__':
    # Run arg parser
    args = get_train_args()

    # Run run experiment
    run_experiment(**args)
