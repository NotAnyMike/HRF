import numpy as np
from pdb import set_trace
from pyglet import gl

from gym.envs.box2d import CarRacing
from gym import spaces
from gym.envs.box2d.car_racing import play, TILE_NAME, default_reward_callback, SOFT_NEG_REWARD, HARD_NEG_REWARD, WINDOW_W, WINDOW_H

from hrl.common.arg_extractor import get_env_args
from hrl.envs import env as environments

class Base(CarRacing):
    def __init__(self, 
            reward_fn=default_reward_callback,
            max_time_out=2.0,
            max_step_reward=1,
            ):
        super(Base,self).__init__(
                allow_reverse=False, 
                grayscale=1,
                show_info_panel=False,
                verbose=0,
                discretize_actions="hard",
                num_tracks=2,
                num_lanes=2,
                num_lanes_changes=0,
                num_obstacles=100,
                max_time_out=max_time_out,
                frames_per_state=4,
                max_step_reward=max_step_reward,
                reward_fn=reward_fn,
                random_obstacle_x_position=False,
                random_obstacle_shape=False,
                )

class Turn(Base):
    def __init__(self):
        def reward_fn(env):
            reward = -SOFT_NEG_REWARD
            done = False

            predictions_id = [id for l in env._next_nodes for id in l.keys() ]
            right_old = env.info['count_right_delay'] > 0
            left_old  = env.info['count_left_delay']  > 0
            not_visited = env.info['visited'] == False
            right = env.info['count_right'] > 0
            left  = env.info['count_left']  > 0
            track0 = env.info['track'] == 0
            track1 = env.info['track'] == 1

            if env.goal_id in np.where(right_old|left_old)[0]:
                # If in objective
                reward += 10
                done = True
            elif (left|right).sum() == 0:
                # In case it is outside the track 
                done = True
                reward -= HARD_NEG_REWARD
            else:
                reward,done = env.check_timeout(reward,done)
                reward,done = env.check_unvisited_tiles(reward,done)
                
                # if still in the prediction set
                if not done and len(list( set(predictions_id) & set(\
                        np.where(not_visited & (right_old|left_old))[0]))) > 0:
        
                    # To allow changes of lane in intersections without lossing points
                    if (left_old & right_old & track0).sum() > 0 and (left_old & right_old & track1).sum() > 0:
                        factor = 2
                    elif (left_old & right_old & track1).sum() > 0 and (((left_old | right_old) & track0).sum() == 0) :
                        factor = 2
                    elif (left_old & right_old & track0).sum() > 0 and (((left_old | right_old) & track1).sum() == 0) :
                        factor = 2
                    else:
                        factor = 1 
                        
                    reward += 1 / factor

            # Cliping reward per episode
            full_reward = reward
            reward = np.clip(
                    reward, env.min_step_reward, env.max_step_reward)

            env.info['visited'][left_old | right_old] = True
            env.info['count_right_delay'] = env.info['count_right']
            env.info['count_left_delay']  = env.info['count_left']
            
            return reward,full_reward,done

        super(Turn,self).__init__(
                reward_fn=reward_fn,
                max_time_out=1.0,
                max_step_reward=10,
                )
        self.goal_id = None
        self.new = True

    def update_contact_with_track(self):
        # Only updating it if still in prediction

        not_visited = self.info['visited'] == False
        right = self.info['count_right'] > 0
        left  = self.info['count_left']  > 0
        predictions_id = [id for l in self._next_nodes for id in l.keys() ]

        # Intersection of the prediction and the set that you are currently in
        if len(list( set(predictions_id) & set(\
                np.where(right|left)[0]))) > 0:
            super(Turn,self).update_contact_with_track()

    def _weak_reset(self):
        """
        This function takes care of ALL the processes to reset the 
        environment, if anything goes wrong, it returns false.
        This is in order to allow several retries to reset 
        the environment
        """
        to_return = super(Turn,self).reset()
        tiles_before = 8
        filter = (self.info['x']) | ((self.info['t']) & (self.info['track'] >0))
        idx = np.random.choice(np.where(filter)[0])

        idx_relative = idx - (self.info['track'] < self.info[idx]['track']).sum()
        if self.info[idx]['end']:
            direction = +1
        elif self.info[idx]['start']:
            direction = -1
        else:
            direction = 1 if np.random.random() < 0.5 else -1
        idx_relative_new = (idx_relative - direction*tiles_before) % len(self.tracks[self.info[idx]['track']])

        idx_new = idx - idx_relative + idx_relative_new
        _,beta,x,y = self._get_rnd_position_inside_lane(idx_new,direction=direction)            

        angle_noise = np.random.uniform(-1,1)*np.pi/12
        beta += angle_noise

        self.place_agent([beta,x,y])
        speed = np.random.uniform(0,100)
        self.set_speed(speed)

        # adding nodes before coming to the intersection
        self._next_nodes = []
        for i in range(tiles_before):
            idx_tmp = (idx_relative - direction*i) % len(self.tracks[self.info[idx]['track']])
            idx_tmp = idx - idx_relative + idx_tmp
            self._next_nodes.append({idx_tmp: {0:-direction,1:-direction}})

        inter = self.understand_intersection(idx,direction)
        
        def get_avg_d_of_segment(idx,direction):
            """
            Calculate the distance of a segment (between two intersections) to
            the center of the map.
            """
            # get the segments
            intersection_id = self.info[idx]['intersection_id']
            track_id = self.info[idx]['track']
            intersections_nodes = np.where((self.info['intersection_id'] != -1) & (self.info['track'] == track_id))[0]
            tmp_pos = np.where(intersections_nodes == idx)[0][0]
            if direction == 1:
                end = idx
                start = intersections_nodes[(tmp_pos-1)%len(intersections_nodes)]
            else:
                start = idx
                end = intersections_nodes[(tmp_pos+1)%len(intersections_nodes)]

            ids = []
            if start > end:
                ids = []
                len_other_tracks = (self.info['track'] < track_id).sum()
                len_track = len(self.tracks[track_id])
                start = start-len_other_tracks
                end   = end-len_other_tracks
                while start != end:
                    ids.append(len_other_tracks+start)
                    start = (start+1)%len_track
                segment = self.track[ids][:,1,2:]
            else:
                ids = list(range(start,end))
                segment = self.track[ids,1,2:]
            avg_d = np.mean(np.linalg.norm(segment, axis=1))
            return avg_d,ids

        ######## adding nodes after the intersection
        # get avg distance from the origin
        intersection_id = self.info[idx]['intersection_id']
        current_track = self.info[idx]['track']
        node_id_main_track = np.where((self.info['intersection_id'] == intersection_id) & (self.info['track'] == 0))[0][0]
        node_id_second_track = np.where((self.info['intersection_id'] == intersection_id) & (self.info['track'] == 1))[0]

        if len(node_id_second_track) == 0:
            # There is no other point in the second track
            return False

        if direction == 1:
            node_id_second_track = node_id_second_track[-1]
        else:
            node_id_second_track = node_id_second_track[0]

        avg_main_track,ids= get_avg_d_of_segment(node_id_main_track, direction)
        # Debugging purposes
        #for i in ids:
        #   self._next_nodes.append({i:{0:direction,1:direction}})

        avg_second_track,ids = get_avg_d_of_segment(node_id_second_track, direction)
        # Debugging purposes
        #for i in ids:
        #    self._next_nodes.append({i:{0:direction,1:direction}})

        # The direction of lane
        flow = self._flow
        if current_track == 0: flow *= -1
        else:
            flow *= (-1 if avg_second_track > avg_main_track else 1)
        if inter[self._direction] is not None:
            for i in range(tiles_before):
                self._next_nodes.append({inter[self._direction]+flow*(i):{0:direction,1:direction}})
        ###########

        self.goal_id = list(self._next_nodes[-1].keys())[0]
        self.new = True
        return to_return
    
    def reset(self):
        while True:
            to_return = self._weak_reset()
            if to_return is not False:
                break
        return to_return

    def _remove_prediction(self, id,lane,direction):
        ###### Removing current new tile from nexts
        pass
        #if len(self._next_nodes) > 0:
            #for tiles in self._next_nodes:
                #if id in tiles:
                    #del tiles[id]

    def _check_predictions(self):
        pass

    #def step(self,action):
        #s,r,d,_ = super(Turn,self).step(action)
        #if self.goal_id in self._current_nodes:
            #d = True
        #return s,r,d,_

    def remove_current_tile(self, id, lane):
        if id in self._current_nodes:
            if len(self._current_nodes[id]) > 1:
                del self._current_nodes[id][lane]
            else:
                del self._current_nodes[id]

class Turn_left(Turn):
    def __init__(self):
        super(Turn_left,self).__init__()
        self._flow = 1
        self._direction = 'left'

class Turn_right(Turn):
    def __init__(self):
        super(Turn_right,self).__init__()
        self._flow = -1
        self._direction = 'right'

class Turn_high(Turn):
    def __init__(self):
        super(Turn_high,self).__init__()

        self._direction = 'right' if np.random.uniform() >= 0.5 else 'left'
        self._flow = -1 if self._direction == 'right' else 1

        self.actions = {}
        self.actions['left']  = Left_policy('weights',self)
        self.actions['right'] = Left_policy('weights',self)

    def _set_config(self, **kwargs):
        super(Turn_high, self)._set_config(**kwargs)
        self.discretize_actions = 'left-right'
        self.action_space = spaces.Discrete(2)

    def reset(self):
        self._direction = 'right' if np.random.uniform() >= 0.5 else 'left'
        self._flow = -1 if self._direction == 'right' else 1
        super(Turn_high,self).reset()

    def step(self,action):
        # transform action
        action = self._transform_high_lvl_action(action)

        # execute transformed action
        state, reward, done, _ = action(self.state)
    
    def raw_step(self,action):
        # Normal step 
        super(Turn_high,self).step(action)

    def _transform_high_lvl_action(self,action):
        if action == 0:
            action = self.actions['left']
        elif action == 1:
            action = self.actions['right']
        return action

    def _render_left(self):
        d = 1 if self._direction == 'right' else 0
        f = self._flow

        # Arrow
        gl.glBegin(gl.GL_TRIANGLES)
        gl.glColor4f(0.7,0,0,1)
        gl.glVertex3f(WINDOW_W*d+f*20, WINDOW_H-80,0)
        gl.glVertex3f(WINDOW_W*d+f*100,WINDOW_H-80-40,0)
        gl.glVertex3f(WINDOW_W*d+f*100,WINDOW_H-80+40,0)
        gl.glEnd()

        # Body
        gl.glBegin(gl.GL_QUADS)
        gl.glColor4f(0.7,0,0,1)
        gl.glVertex3f(WINDOW_W*d+f*100,WINDOW_H-80+15,0)
        gl.glVertex3f(WINDOW_W*d+f*150,WINDOW_H-80+15,0)
        gl.glVertex3f(WINDOW_W*d+f*150,WINDOW_H-80-15,0)
        gl.glVertex3f(WINDOW_W*d+f*100,WINDOW_H-80-15,0)
        gl.glEnd()

    def _render_additional_objects(self):
        self._render_left()

if __name__=='__main__':
    args = get_env_args()
    env = getattr(environments, args.env)()
    play(env)
