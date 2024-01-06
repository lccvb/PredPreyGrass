"""
[v34]
-implement bar chart which tracks energy levels per agent/type of agent
-death of Predator (and Prey) by starvation (implement minimum energy levels
-tried A2C with 4 predators and 8 prey, but it did not learn well
[v35]
-implement self.grass_position_dict and self.prey_position_dict for more 
efficient removal of grass and prey
-stop when all prey are eaten OR all predators are dead



TODO Later
-directly remove grass from grass_instance_list when eaten by prey and not via 
grass_to_be_removed_by_prey_dict in the last step of the cycle
-if masking actions does not work, maybe penalizing actions do work via rewards.
-Birth of agents Predators, Prey and Grass
-personalize reward per agent/type
-when annimals startve no directly vanish but remains there for scavenget agents
-introduce altruistic agents as in the NetLogo
-implement Torus grid:
------------------------------------------------------
for i in [-1, 0, 1]:
    for j in [-1, 0, 1]:
        x_target = (self.x_position + i) % matrix.xDim
        y_target = (self.y_position + j) % matrix.yDim
------------------------------------------------------
-specify (not)Moore per agent by masking?
-visualize energy levels per agent
-reward structure: action stay less energy than moving
-energy loss depending on distance moved?
-continuous observation space
Why PPO pauses training after 250K steps or so?
If so, this is due to the flow of the training algorithm.
Talking in the case of PPO, at first data is sampled from every agent.
The collected data is then used to update the agent's policy (this is the observed break).
Data is always collected with the most recent policy.

"""

# noqa: D212, D415

from collections import defaultdict
import numpy as np
import pygame
import random

import gymnasium
from gymnasium import spaces
from gymnasium.utils import seeding, EzPickle

from pettingzoo import AECEnv
from pettingzoo.utils import agent_selector
import os
# position of the pygame window on the screen
x_pygame_window = 0
y_pygame_window = 0


class DiscreteAgent():
    def __init__(
        self,
        x_grid_size,
        y_grid_size,
        agent_type_nr, # 0: wall, 1: prey, 2: grass, 3: predator
        agent_id_nr,
        agent_name,
        observation_range=7,
        n_channels=4, # n channels is the number of observation channels
        flatten=False,  
        motion_range = [
                [-1, 0], # move left
                [0, -1], # move up
                [0, 0], # stay
                [0, 1], # move down
                [1, 0], # move right
                ],
        initial_energy=10,
        catch_grass_reward=5.0,
        catch_prey_reward=5.0,
        energy_loss_per_step=-0.1

    ):
        #identification agent
        self.agent_type_nr = agent_type_nr   # also channel number of agent 
        self.agent_name = agent_name   # string like "prey_1"
        self.agent_id_nr = agent_id_nr       # unique integer per agent

        #(fysical) boundaries/limitations agent in observing (take in) and acting (take out)
        self.x_grid_size = x_grid_size
        self.y_grid_size = y_grid_size
        self.observation_range = observation_range
        self.observation_shape = (n_channels * observation_range**2 + 1,) if flatten else \
            (observation_range, observation_range, n_channels)
        self.motion_range = motion_range
        self.n_actions_agent=len(self.motion_range)   
        self.action_space_agent = spaces.Discrete(self.n_actions_agent) 
        self.position = np.zeros(2, dtype=np.int32)  # x and y position
        self.energy = initial_energy  # still to implement
        self.energy_loss_per_step = energy_loss_per_step
        self.catch_grass_reward = catch_grass_reward
        self.catch_prey_reward = catch_prey_reward

    def step(self, action):
        # returns new position of agent "self" given action "action"
        next_position = np.zeros(2, dtype=np.int32) 
        next_position[0], next_position[1] = self.position[0], self.position[1]
        next_position += self.motion_range[action]
        # masking
        if not (0 <= next_position[0] < self.x_grid_size and 
                            0 <= next_position[1] < self.y_grid_size):
            return self.position   # if moved out of borders: dont move
        else:
            self.position = next_position
            return self.position

class AgentLayer:
    def __init__(self, xs, ys, ally_agents_instance_list):

        self.ally_agents_instance_list = ally_agents_instance_list
        self.n_ally_agents = len(ally_agents_instance_list)
        self.global_state_ally_agents = np.zeros((xs, ys), dtype=np.int32)

    def n_ally_layer_agents(self):
        return self.n_ally_agents

    def move_agent_instance(self, agent_instance, action):
        
        return agent_instance.step(action)

    def get_position_agent_instance(self, agent_instance):
        return agent_instance.position
  
    def remove_agent_instance(self, agent_instance):
        if agent_instance not in self.ally_agents_instance_list:
            #print(agent_instance.agent_name, " not in ally_agents_instance_list")
            #print("ally_agents_instance_list = ", self.ally_agents_instance_list)
            raise ValueError("agent_instance not in ally_agents_instance_list")
        self.ally_agents_instance_list.remove(agent_instance)
        self.n_ally_agents -= 1              

    def get_global_state_ally_agents(self):
        global_state_ally_agents = self.global_state_ally_agents
        global_state_ally_agents.fill(0)
        for ally_agent_instance in self.ally_agents_instance_list:
            x, y = ally_agent_instance.position
            global_state_ally_agents[x, y] += 1
        return global_state_ally_agents

class PredPrey:
    def __init__(
        self,
        x_grid_size: int = 16,
        y_grid_size: int = 16,
        max_cycles: int = 500,
        n_predator: int = 4,
        n_prey: int = 4,
        n_grass: int = 10,
        max_observation_range: int = 7,
        obs_range_predator: int = 7,
        obs_range_prey: int = 7,
        freeze_grass: bool = False,
        render_mode = None,
        action_range: int = 5,
        moore_neighborhood_actions: bool = False,   
        energy_loss_per_step_predator = -0.2,
        energy_loss_per_step_prey = -0.1,     
        initial_energy_predator = 10.0,
        initial_energy_prey = 8.0,
        cell_scale: int = 40,
        x_pygame_window : int = 0,
        y_pygame_window : int = 0,
        catch_grass_reward=5.0,
        catch_prey_reward=5.0,
        ):
        #parameter init
        self.x_grid_size = x_grid_size
        self.y_grid_size = y_grid_size
        self.max_cycles = max_cycles
        self.n_predator = n_predator
        self.n_prey = n_prey
        self.n_grass = n_grass
        self.max_observation_range = max_observation_range
        self.obs_range_predator = obs_range_predator        
        self.obs_range_prey = obs_range_prey
        self.freeze_grass = freeze_grass
        self.render_mode = render_mode
        self.action_range = action_range
        self.moore_neighborhood_actions = moore_neighborhood_actions
        self.energy_loss_per_step_predator = energy_loss_per_step_predator
        self.energy_loss_per_step_prey = energy_loss_per_step_prey
        self.cell_scale = cell_scale
        self.initial_energy_predator = initial_energy_predator
        self.initial_energy_prey = initial_energy_prey
        self.x_pygame_window = x_pygame_window
        self.y_pygame_window = y_pygame_window
        self.catch_grass_reward = catch_grass_reward
        self.catch_prey_reward = catch_prey_reward

        os.environ['SDL_VIDEO_WINDOW_POS'] = "%d,%d" % (self.x_pygame_window, 
                                                        self.y_pygame_window)

        self._seed()
        self.agent_id_counter = 0

        # agent types
        self.agent_type_names = ["wall", "predator", "prey", "grass"]  # different types of agents 
        self.predator_type_nr = self.agent_type_names.index("predator") #1
        self.prey_type_nr = self.agent_type_names.index("prey")  #2
        self.grass_type_nr = self.agent_type_names.index("grass")  #3
        
        # lists of agents
        # initialization
        self.predator_instance_list = [] # list of all living predator
        self.prey_instance_list = [] # list of all living prey
        self.grass_instance_list = [] # list of all living grass
        self.agent_instance_list = [] # list of all living agents
        self.predator_name_list = []
        self.prey_name_list = []
        self.grass_name_list = []

        self.grass_instance_position_dict = {}
        self.grass_name_position_dict = {}
        self.prey_position_dict = {}
 
        self.agent_name_to_instance_dict = dict()
        # 'n_agents' is the PredPrey equivalent of PettingZoo 'num_agents' in raw_env
        self.n_agents = self.n_predator + self.n_prey

        # creation agent type lists
        self.predator_name_list =  ["predator" + "_" + str(a) for a in range(self.n_predator)]
        self.prey_name_list =  ["prey" + "_" + str(a) for a in range(self.n_predator, self.n_prey+self.n_predator)]
        self.agent_name_list = self.predator_name_list + self.prey_name_list
        self.predator_alive_dict = dict(zip(self.predator_name_list, [True for _ in self.predator_name_list]))
        self.prey_alive_dict = dict(zip(self.prey_name_list, [True for _ in self.prey_name_list]))
        self.grass_alive_dict = dict(zip(self.grass_name_list, [True for _ in self.grass_name_list]))


        # observations
        max_agents_overlap = max(self.n_prey, self.n_predator, self.n_grass)
        self.max_obs_offset = int((self.max_observation_range - 1) / 2) 
        self.nr_observation_channels = len(self.agent_type_names)
        obs_space = spaces.Box(
            low=0,
            high=max_agents_overlap,
            shape=(self.max_observation_range, self.max_observation_range, self.nr_observation_channels),
            dtype=np.float32,
        )
        self.observation_space = [obs_space for _ in range(self.n_agents)]  # type: ignore
        self.obs_spaces_test = []
        # end observations

        # actions
        action_offset = int((self.action_range - 1) / 2) 
        action_range_iterator = list(range(-action_offset, action_offset+1))
        self.motion_range = []
        action_nr = 0
        for d_x in action_range_iterator:
            for d_y in action_range_iterator:
                if moore_neighborhood_actions:
                    self.motion_range.append([d_x,d_y]) 
                    action_nr += 1
                elif abs(d_x) + abs(d_y) <= action_offset:
                    self.motion_range.append([d_x,d_y])        
                    action_nr += 1
     
        self.n_actions_agent=len(self.motion_range)
        action_space_agent = spaces.Discrete(self.n_actions_agent)  
        self.action_space = [action_space_agent for _ in range(self.n_agents)] # type: ignore
                  
        # end actions

        # grid list: agent_instances in grid location
        self.agents_instances_in_grid_location = []

        for obs_channel in range(self.nr_observation_channels):
            self.agents_instances_in_grid_location.append({})
        # initialization
        
        for obs_channel in range(self.nr_observation_channels):
            for x in range(self.x_grid_size):
                for y in range(self.y_grid_size):
                    self.agents_instances_in_grid_location[obs_channel][x,y] = []
        # end agent_name in grid location

        # removal agents
        self.prey_who_remove_grass_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
        self.grass_to_be_removed_by_prey_dict = dict(zip(self.grass_name_list, [False for _ in self.grass_name_list]))
        self.predator_who_remove_prey_dict = dict(zip(self.predator_name_list, [False for _ in self.predator_name_list])) 
        self.prey_to_be_removed_by_predator_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
        self.predator_to_be_removed_by_starvation_dict = dict(zip(self.predator_name_list, [False for _ in self.predator_name_list]))
        self.prey_to_be_removed_by_starvation_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))

        # end removal agents


        # visualization
        self.screen = None
        self.save_image_steps = False
        self.width_energy_chart = 800
        self.height_energy_chart = self.cell_scale * self.y_grid_size
        # end visualization
        self.file_name = 0
        self.n_aec_cycles = 0
        # end visualization

    def add_grass_instance_to_grass_position_dict(self, grass_instance):
        position = tuple(grass_instance.position)
        if position not in self.grass_instance_position_dict:
            self.grass_instance_position_dict[position] = []
        self.grass_instance_position_dict[position].append(grass_instance)

    def add_grass_name_to_grass_position_dict(self, grass_instance):
        position = tuple(grass_instance.position)
        if position not in self.grass_name_position_dict:
            self.grass_name_position_dict[position] = []
        self.grass_name_position_dict[position].append(grass_instance.agent_name)

    def remove_grass_instance_from_grass_position_dict(self, grass_instance):
        position = tuple(grass_instance.position)
        self.grass_instance_position_dict[position].remove(grass_instance)
 
    def remove_grass_name_from_grass_position_dict(self, grass_instance):
        position = tuple(grass_instance.position)
        self.grass_name_position_dict[position].remove(grass_instance.agent_name)
 
    def add_prey_to_prey_position_dict(self, prey_instance):
        position = tuple(prey_instance.position)
        if position not in self.prey_position_dict:
            self.prey_position_dict[position] = []
        self.prey_position_dict[position].append(prey_instance)

    def remove_prey_from_prey_position_dict(self, prey_instance):
        position = tuple(prey_instance.position)
        self.prey_position_dict[position].remove(prey_instance)
        if not self.prey_position_dict[position]:
            del self.prey_position_dict[position]

    def create_agent_instance_list(
            self, 
            n_agents,
            agent_type_nr,
            observation_range, 
            randomizer, 
            flatten=False,
            energy_loss_per_step = -0.1,
            initial_energy = 10
            ):

        _agent_instance_list = []

        agent_type_name = self.agent_type_names[agent_type_nr]
        for _ in range(n_agents): 
            agent_id_nr = self.agent_id_counter           
            agent_name = agent_type_name + "_" + str(agent_id_nr)
            self.agent_id_counter+=1
            xinit, yinit = (randomizer.integers(0, self.x_grid_size), randomizer.integers(0, self.y_grid_size))      

            agent_instance = DiscreteAgent(
                self.x_grid_size, 
                self.y_grid_size, 
                agent_type_nr, 
                agent_id_nr,
                agent_name,
                observation_range=observation_range, 
                flatten=flatten, 
                motion_range=self.motion_range,
                initial_energy=initial_energy,
                catch_grass_reward=self.catch_grass_reward,
                catch_prey_reward=self.catch_prey_reward,
                energy_loss_per_step=energy_loss_per_step
            )
            #  updates lists en records
 
            self.agents_instances_in_grid_location[agent_type_nr][xinit,yinit].append(agent_instance)
 
            self.agent_name_to_instance_dict[agent_name] = agent_instance
            agent_instance.position = (xinit, yinit)  
            _agent_instance_list.append(agent_instance)
        return _agent_instance_list

    def reset(self):
        # empty agent lists
        self.predator_instance_list =[]
        self.prey_instance_list =[]
        self.grass_instance_list = []
        self.agent_instance_list = []

        self.predator_name_list =[]
        self.prey_name_list =[]
        self.grass_name_list = []
        self.agent_name_list = []

        self.grass_instance_position_dict = {}
        self.grass_name_position_dict = {}
        self.prey_position_dict = {}
        for i in range(self.x_grid_size):
            for j in range(self.y_grid_size):
                self.grass_instance_position_dict[(i,j)] = []
        #print("self.grass_instance_position_dict = ", self.grass_instance_position_dict)


        self.agent_id_counter = 0
        self.agent_name_to_instance_dict = {}        
        self.model_state = np.zeros((self.nr_observation_channels, self.x_grid_size, self.y_grid_size), dtype=np.float32)
  
        #list agents consisting of predator agents
        self.predator_instance_list = self.create_agent_instance_list(
            self.n_predator, 
            self.predator_type_nr, 
            self.obs_range_predator,
            self.np_random,
            energy_loss_per_step=self.energy_loss_per_step_predator,
            initial_energy=self.initial_energy_predator
        )
        self.predator_name_list =  self.create_agent_name_list_from_instance_list(
            self.predator_instance_list
        )
        # list agents consisting of prey agents
        self.prey_instance_list = self.create_agent_instance_list(
            self.n_prey, 
            self.prey_type_nr, 
            self.obs_range_prey, 
            self.np_random, 
            energy_loss_per_step =self.energy_loss_per_step_prey,
            initial_energy=self.initial_energy_prey
        )
        self.prey_name_list =  self.create_agent_name_list_from_instance_list(
            self.prey_instance_list
        )
        self.grass_instance_list = self.create_agent_instance_list(            
            self.n_grass, 
            self.grass_type_nr, 
            0,  # grass observation range is zero
            self.np_random, 
        ) 
        self.grass_name_list =  self.create_agent_name_list_from_instance_list(
            self.grass_instance_list
        )
        # 
        for grass_instance in self.grass_instance_list:
            self.add_grass_instance_to_grass_position_dict(grass_instance)
            #self.add_grass_name_to_grass_position_dict(grass_instance)


        for prey_instance in self.prey_instance_list:
            self.add_prey_to_prey_position_dict(prey_instance)

        # removal agents set to false
        self.prey_who_remove_grass_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
        self.grass_to_be_removed_by_prey_dict = dict(zip(self.grass_name_list, [False for _ in self.grass_name_list]))

        # agents alive set to True
        self.grass_alive_dict = dict(zip(self.grass_name_list, [True for _ in self.grass_name_list]))
        self.prey_alive_dict = dict(zip(self.prey_name_list, [True for _ in self.prey_name_list]))
        self.predator_alive_dict = dict(zip(self.predator_name_list, [True for _ in self.predator_name_list]))
        # end removal agents

        self.agent_instance_list = self.predator_instance_list + self.prey_instance_list        
        self.agent_name_list = self.predator_name_list + self.prey_name_list

        self.predator_layer = AgentLayer(self.x_grid_size, self.y_grid_size, self.predator_instance_list)
        self.prey_layer = AgentLayer(self.x_grid_size, self.y_grid_size, self.prey_instance_list)
        self.grass_layer = AgentLayer(self.x_grid_size, self.y_grid_size, self.grass_instance_list)

        self.agent_reward_dict = dict(zip(self.agent_name_list, 
                                          [0.0 for _ in self.agent_name_list]))

    
        self.model_state[self.predator_type_nr] = self.predator_layer.get_global_state_ally_agents()
        self.model_state[self.prey_type_nr] = self.prey_layer.get_global_state_ally_agents()
        self.model_state[self.grass_type_nr] = self.grass_layer.get_global_state_ally_agents()

        self.n_aec_cycles = 0

    def observation_space(self, agent):
        return self.observation_spaces[agent] # type: ignore

    def close(self):
        if self.screen is not None:
            pygame.quit()
            self.screen = None

    def _seed(self, seed=None):
        self.np_random, seed_ = seeding.np_random(seed)
        return [seed_]

    def step(self, action, agent_instance, is_last):
        # Extract agent details
        agent_type_nr = agent_instance.agent_type_nr
        agent_name = agent_instance.agent_name
        agent_energy = agent_instance.energy
        agent_position = agent_instance.position

        # If the agent is a predator and it's alive
        if agent_type_nr == self.predator_type_nr and self.predator_alive_dict[agent_name]: 
            if agent_energy > 0: # If predator has energy
                # Move the predator and update the model state
                self.predator_layer.move_agent_instance(agent_instance, action)
                self.model_state[self.predator_type_nr] = self.predator_layer.get_global_state_ally_agents()
        
                # If there's prey at the new position, remove (eat) one at random
                x_new_position_predator, y_new_position_predator = agent_position
                if self.model_state[self.prey_type_nr, x_new_position_predator, y_new_position_predator] > 0:
                    prey_instance_list_in_cell_predator = self.prey_position_dict[(x_new_position_predator, y_new_position_predator)]
                    prey_instance_removed = random.choice(prey_instance_list_in_cell_predator)
                    self.predator_who_remove_prey_dict[agent_name] = True
                    self.prey_to_be_removed_by_predator_dict[prey_instance_removed.agent_name] = True
            else:  # If predator has no energy, it starves to death
                self.predator_to_be_removed_by_starvation_dict[agent_name] = True

        # If the agent is a prey and it's alive
        elif agent_type_nr == self.prey_type_nr and self.prey_alive_dict[agent_name]:
            if agent_energy > 0:  # If prey has energy
                # Move the prey and update the model state
                self.remove_prey_from_prey_position_dict(agent_instance)
                self.prey_layer.move_agent_instance(agent_instance, action)
                self.add_prey_to_prey_position_dict(agent_instance)
                self.model_state[self.prey_type_nr] = self.prey_layer.get_global_state_ally_agents()
                x_new_position_prey, y_new_position_prey = agent_position

                # If there's grass at the new position, remove (eat) one at random
                # second conditons is to prevent searchin an empty list when another prey in the same cycle
                # already selected the only grass instance for removal earlier in the same cycle
                if self.model_state[self.grass_type_nr, x_new_position_prey, y_new_position_prey] > 0 and self.grass_instance_position_dict[(x_new_position_prey, y_new_position_prey)]:
                    grass_instance_list_in_cell_prey = self.grass_instance_position_dict[(x_new_position_prey, y_new_position_prey)]
                    grass_instance_removed = random.choice(grass_instance_list_in_cell_prey)
                    grass_name_removed = grass_instance_removed.agent_name
                    # condition for when grass was already selected for removal by another prey agent in the same cycle
                    self.prey_who_remove_grass_dict[agent_name] = True
                    self.grass_to_be_removed_by_prey_dict[grass_name_removed] = True
                    # Immediately remove the grass instance from the position dict
                    # to prevent eating the same grass instance twice by different prey in the same cycle
                    # This way, the same grass agent cannot be selected for removal by another prey agent in the same cycle.
                    self.remove_grass_instance_from_grass_position_dict(grass_instance_removed)
                    #self.remove_grass_name_from_grass_position_dict(grass_instance_removed)

            else: # prey starves to death
                self.prey_to_be_removed_by_starvation_dict[agent_name] = True

        # reset rewards to zero during every step
        self.agent_reward_dict = dict(zip(self.agent_name_list, 
                                          [0.0 for _ in self.agent_name_list]))

        if is_last: # removes agents and reap rewards at the end of the cycle
            for predator_name in self.predator_name_list:
                if self.predator_alive_dict[predator_name]:
                    predator_instance = self.agent_name_to_instance_dict[predator_name]
                    # remove predator which starves to death
                    if self.predator_to_be_removed_by_starvation_dict[predator_name]:
                        self.predator_layer.remove_agent_instance(predator_instance)
                        self.model_state[self.predator_type_nr] = self.predator_layer.get_global_state_ally_agents()
                        self.predator_alive_dict[predator_name] = False
                        predator_instance.energy = 0.0
                    else: # reap rewards for predator which removes prey
                        catch_reward_predator = predator_instance.catch_prey_reward * self.predator_who_remove_prey_dict[predator_name] 
                        step_reward_predator = predator_instance.energy_loss_per_step
                        self.agent_reward_dict[predator_name] += step_reward_predator
                        self.agent_reward_dict[predator_name] += catch_reward_predator
                        # TODO: energy and rewards integrated in future?
                        predator_instance.energy += step_reward_predator 
                        predator_instance.energy += catch_reward_predator
                        #print(predator_name," has energy: ",round(predator_instance.energy,1))
            for prey_name in self.prey_name_list:
                if self.prey_alive_dict[prey_name]:
                    prey_instance = self.agent_name_to_instance_dict[prey_name]
                    # remove prey which gets eaten by a predator or starves to death
                    if self.prey_to_be_removed_by_predator_dict[prey_name] or self.prey_to_be_removed_by_starvation_dict[prey_name]:
                        self.prey_layer.remove_agent_instance(prey_instance)
                        self.model_state[self.prey_type_nr] = self.prey_layer.get_global_state_ally_agents() #
                        self.prey_alive_dict[prey_name] = False
                        prey_instance.energy = 0.0
                        self.remove_prey_from_prey_position_dict(prey_instance)
                    else: # reap rewards for prey which removes grass
                        #self.agent_reward_dict[prey_name] += -number_of_predators_in_observation
                        catch_reward_prey = prey_instance.catch_grass_reward * self.prey_who_remove_grass_dict[prey_name] 
                        step_reward_prey = prey_instance.energy_loss_per_step
                        # this is not cumulative reward, agent_reward_dict is set to zero before 'last' step
                        self.agent_reward_dict[prey_name] += step_reward_prey
                        self.agent_reward_dict[prey_name] += catch_reward_prey
                        prey_instance.energy += step_reward_prey
                        prey_instance.energy += catch_reward_prey
            for grass_name in self.grass_name_list:
                grass_instance = self.agent_name_to_instance_dict[grass_name]
                #print("grass_name = ", grass_name)
                #print("self.grass_to_be_removed_by_prey_dict ",self.grass_to_be_removed_by_prey_dict)
                # remove grass which gets eaten by a prey
                if self.grass_to_be_removed_by_prey_dict[grass_name]:
                    #removes grass_name from 'grass_name_list'
                    #print("grass_name = ", grass_name, " is removed from position ",grass_instance.position)
                    #print("grass_name_position_dict = ", self.grass_name_position_dict) 
                    #print("grass_instance_position_dict = ", self.grass_instance_position_dict)
                    #print()
                    self.grass_layer.remove_agent_instance(grass_instance)
                    self.model_state[self.grass_type_nr] = self.grass_layer.get_global_state_ally_agents()
                    #self.remove_grass_instance_from_grass_position_dict(grass_instance)

            self.n_aec_cycles = self.n_aec_cycles + 1
            #reinit agents records to default at the end of the cycle
            self.prey_who_remove_grass_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
            self.grass_to_be_removed_by_prey_dict = dict(zip(self.grass_name_list, [False for _ in self.grass_name_list]))
            self.predator_who_remove_prey_dict = dict(zip(self.predator_name_list, [False for _ in self.predator_name_list])) 
            self.prey_to_be_removed_by_predator_dict = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
            self.predator_to_be_removed_by_starvation_dict = dict(zip(self.predator_name_list, [False for _ in self.predator_name_list]))
            # end reinit agents records to default at the end of the cycle

        if self.render_mode == "human":
            self.render()

    def create_agent_name_list_from_instance_list(self, _agent_instance_list):
        _agent_name_list = []
        for agent_instance in _agent_instance_list:
            _agent_name_list.append(agent_instance.agent_name)
        return _agent_name_list
            
    @property
    def is_no_grass(self):
        if self.grass_layer.n_ally_layer_agents() == 0:
            return True
        return False

    @property
    def is_no_prey(self):
        if self.prey_layer.n_ally_layer_agents() == 0:
            return True
        return False

    @property
    def is_no_predator(self):
        if self.predator_layer.n_ally_layer_agents() == 0:
            return True
        return False

    def observe(self, agent_name):

        agent_instance = self.agent_name_to_instance_dict[agent_name]
        
        xp, yp = agent_instance.position[0], agent_instance.position[1]

        # returns a flattened array of all the observations
        observation = np.zeros((self.nr_observation_channels, self.max_observation_range, self.max_observation_range), dtype=np.float32)
        observation[0].fill(1.0)  

        xlo, xhi, ylo, yhi, xolo, xohi, yolo, yohi = self.obs_clip(xp, yp)

        observation[0:self.nr_observation_channels, xolo:xohi, yolo:yohi] = np.abs(self.model_state[0:self.nr_observation_channels, xlo:xhi, ylo:yhi])
        
        observation_range_agent = agent_instance.observation_range
        max = self.max_observation_range
        #mask is number of 'outer squares' of an observation surface set to zero
        mask = int((max - observation_range_agent)/2)
        if mask > 0: # observation_range agent is smaller than default max_observation_range
            for j in range(mask):
                for i in range(self.nr_observation_channels):
                    observation[i][j,0:max] = 0
                    observation[i][max-1-j,0:max] = 0
                    observation[i][0:max,j] = 0
                    observation[i][0:max,max-1-j] = 0
            return observation
        elif mask == 0:
            return observation
        else:
            raise Exception(
                "Error: observation_range_agent larger than max_observation_range"
                )

    def obs_clip(self, x, y):
        xld = x - self.max_obs_offset
        xhd = x + self.max_obs_offset
        yld = y - self.max_obs_offset
        yhd = y + self.max_obs_offset
        xlo, xhi, ylo, yhi = (
            np.clip(xld, 0, self.x_grid_size - 1),
            np.clip(xhd, 0, self.x_grid_size - 1),
            np.clip(yld, 0, self.y_grid_size - 1),
            np.clip(yhd, 0, self.y_grid_size - 1),
        )
        xolo, yolo = abs(np.clip(xld, -self.max_obs_offset, 0)), abs(
            np.clip(yld, -self.max_obs_offset, 0)
        )
        xohi, yohi = xolo + (xhi - xlo), yolo + (yhi - ylo)
        return xlo, xhi + 1, ylo, yhi + 1, xolo, xohi + 1, yolo, yohi + 1

    def draw_grid_model(self):
        x_len, y_len = (self.x_grid_size, self.y_grid_size)
        for x in range(x_len):
            for y in range(y_len):
                # Draw white cell
                cell_pos = pygame.Rect(
                    self.cell_scale * x,
                    self.cell_scale * y,
                    self.cell_scale,
                    self.cell_scale,
                )
                cell_color = (255, 255, 255)  # white background
                pygame.draw.rect(self.screen, cell_color, cell_pos)

                # Draw black border around cells
                border_pos = pygame.Rect(
                    self.cell_scale * x,
                    self.cell_scale * y,
                    self.cell_scale,
                    self.cell_scale,
                )
                border_color = (192, 192, 192)  # light grey border around cells
                pygame.draw.rect(self.screen, border_color, border_pos, 1)

        # Draw red border around total grid
        border_pos = pygame.Rect(
            0,
            0,
            self.cell_scale * x_len,
            self.cell_scale * y_len,
        )
        border_color = (255, 0, 0) # red
        pygame.draw.rect(self.screen, border_color, border_pos, 5) # type: ignore

    def draw_predator_observations(self):
        for predator_instance in self.predator_instance_list:
            position =  predator_instance.position 
            x = position[0]
            y = position[1]
            mask = int((self.max_observation_range - predator_instance.observation_range)/2)
            if mask == 0:
                patch = pygame.Surface(
                    (self.cell_scale * self.max_observation_range, self.cell_scale * self.max_observation_range)
                )
                patch.set_alpha(128)
                patch.fill((255, 152, 72))
                ofst = self.max_observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.cell_scale * (x - ofst + 1 / 2),
                        self.cell_scale * (y - ofst + 1 / 2),
                    ),
                )
            else:
                patch = pygame.Surface(
                    (self.cell_scale * predator_instance.observation_range, self.cell_scale * predator_instance.observation_range)
                )
                patch.set_alpha(128)
                patch.fill((255, 152, 72))
                ofst = predator_instance.observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.cell_scale * (x - ofst + 1 / 2),
                        self.cell_scale * (y - ofst + 1 / 2),
                    ),
                )

    def draw_prey_observations(self):
        for prey_instance in self.prey_instance_list:
            position =  prey_instance.position 
            x = position[0]
            y = position[1]
            mask = int((self.max_observation_range - prey_instance.observation_range)/2)
            if mask == 0:
                patch = pygame.Surface(
                    (self.cell_scale * self.max_observation_range, self.cell_scale * self.max_observation_range)
                )
                patch.set_alpha(128)
                patch.fill((72, 152, 255))
                ofst = self.max_observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.cell_scale * (x - ofst + 1 / 2),
                        self.cell_scale * (y - ofst + 1 / 2),
                    ),
                )
            else:
                patch = pygame.Surface(
                    (self.cell_scale * prey_instance.observation_range, self.cell_scale * prey_instance.observation_range)
                )
                patch.set_alpha(128)
                patch.fill((72, 152, 255))
                ofst = prey_instance.observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.cell_scale * (x - ofst + 1 / 2),
                        self.cell_scale * (y - ofst + 1 / 2),
                    ),
                )

    def draw_predator_instances(self):
        for predator_instance in self.predator_instance_list:
            position =  predator_instance.position 
            x = position[0]
            y = position[1]

            center = (
                int(self.cell_scale * x + self.cell_scale / 2),
                int(self.cell_scale * y + self.cell_scale / 2),
            )

            col = (255, 0, 0) # red

            pygame.draw.circle(self.screen, col, center, int(self.cell_scale / 3)) # type: ignore

    def draw_prey_instances(self):
        for prey_instance in self.prey_instance_list:
            position =  prey_instance.position 
            x = position[0]
            y = position[1]

            center = (
                int(self.cell_scale * x + self.cell_scale / 2),
                int(self.cell_scale * y + self.cell_scale / 2),
            )

            col = (0, 0, 255) # blue

            pygame.draw.circle(self.screen, col, center, int(self.cell_scale / 3)) # type: ignore

    def draw_grass_instances(self):
        for grass_instance in self.grass_instance_list:

            position =  grass_instance.position 
            #print(grass_instance.agent_name," at position ", position)
            x = position[0]
            y = position[1]

            center = (
                int(self.cell_scale * x + self.cell_scale / 2),
                int(self.cell_scale * y + self.cell_scale / 2),
            )

            col = (0, 128, 0) # green

            #col = (0, 0, 255) # blue

            pygame.draw.circle(self.screen, col, center, int(self.cell_scale / 3)) # type: ignore

    def draw_agent_instance_id_nrs(self):
        font = pygame.font.SysFont("Comic Sans MS", self.cell_scale * 2 // 3)

        predator_positions = defaultdict(int)
        prey_positions = defaultdict(int)
        grass_positions = defaultdict(int)

        for predator_instance in self.predator_instance_list:
            prey_position =  predator_instance.position 
            x = prey_position[0]
            y = prey_position[1]
            predator_positions[(x, y)] = predator_instance.agent_id_nr

        for prey_instance in self.prey_instance_list:
            prey_position =  prey_instance.position 
            x = prey_position[0]
            y = prey_position[1]
            prey_positions[(x, y)] = prey_instance.agent_id_nr

        for grass_instance in self.grass_instance_list:
            grass_position =  grass_instance.position 
            x = grass_position[0]
            y = grass_position[1]
            grass_positions[(x, y)] = grass_instance.agent_id_nr

        for x, y in predator_positions:
            (pos_x, pos_y) = (
                self.cell_scale * x + self.cell_scale // 3.4,
                self.cell_scale * y + self.cell_scale // 1.2,
            )

            predator_id_nr__text =str(predator_positions[(x, y)])

            predator_text = font.render(predator_id_nr__text, False, (255, 255, 0))

            self.screen.blit(predator_text, (pos_x, pos_y - self.cell_scale // 2))

        for x, y in prey_positions:
            (pos_x, pos_y) = (
                self.cell_scale * x + self.cell_scale // 3.4,
                self.cell_scale * y + self.cell_scale // 1.2,
            )

            prey_id_nr__text =str(prey_positions[(x, y)])

            prey_text = font.render(prey_id_nr__text, False, (255, 255, 0))

            self.screen.blit(prey_text, (pos_x, pos_y - self.cell_scale // 2))

        for x, y in grass_positions:
            (pos_x, pos_y) = (
                self.cell_scale * x + self.cell_scale // 3.4,
                self.cell_scale * y + self.cell_scale // 1.2,
            )

            grass_id_nr__text =str(grass_positions[(x, y)])

            grass_text = font.render(grass_id_nr__text, False, (255, 255, 0))

            self.screen.blit(grass_text, (pos_x, pos_y - self.cell_scale // 2))

    def draw_white_canvas_energy_chart(self):
        # relative position of energy chart within pygame window
        x_position_energy_chart = self.cell_scale*self.x_grid_size
        y_position_energy_chart = 0 #self.y_pygame_window
        pos = pygame.Rect(
            x_position_energy_chart,
            y_position_energy_chart,
            self.width_energy_chart,
            self.height_energy_chart,
        )
        color = (255, 255, 255) # white background                
        pygame.draw.rect(self.screen, color, pos) # type: ignore

    def draw_bar_chart_energy(self):
        chart_title = "Energy levels agents"
        # Draw chart title
        title_x = 1000
        title_y = 30
        title_color = (0, 0, 0)  # black
        font = pygame.font.Font(None, 30)
        title_text = font.render(chart_title, True, title_color)
        self.screen.blit(title_text, (title_x, title_y))
        # Draw predator bars
        data_predators = []
        for predator_name in self.predator_name_list:
            predator_instance = self.agent_name_to_instance_dict[predator_name]
            predator_energy = predator_instance.energy
            data_predators.append(predator_energy)
            #print(predator_name," has energy", round(predator_energy,1))
        x_screenposition = 400   
        y_screenposition = 50
        bar_width = 20
        offset_bars = 20
        height = 500
        max_energy_value_chart = 30
        for i, value in enumerate(data_predators):
            bar_height = (value / max_energy_value_chart) * height
            bar_x = x_screenposition + (self.width_energy_chart - (bar_width * len(data_predators))) // 2 + i * (bar_width+offset_bars)
            bar_y = y_screenposition + height - bar_height

            color = (255, 0, 0)  # blue

            pygame.draw.rect(self.screen, color, (bar_x, bar_y, bar_width, bar_height))

        # Draw y-axis
        y_axis_x = x_screenposition + (self.width_energy_chart - (bar_width * len(data_predators))) // 2 - 10
        y_axis_y = y_screenposition
        y_axis_height = height + 10
        y_axis_color = (0, 0, 0)  # black
        pygame.draw.rect(self.screen, y_axis_color, (y_axis_x, y_axis_y, 5, y_axis_height))

        # Draw x-axis
        x_axis_x = x_screenposition + 15 + (self.width_energy_chart - (bar_width * len(data_predators))) // 2 - 10
        x_axis_y = y_screenposition + height
        x_axis_width = self.width_energy_chart - 120
        x_axis_color = (0, 0, 0)  # black
        pygame.draw.rect(self.screen, x_axis_color, (x_axis_x, x_axis_y, x_axis_width, 5))

        # Draw tick labels predators on x-axis
        for i, predator_name in enumerate(self.predator_name_list):
            predator_instance = self.agent_name_to_instance_dict[predator_name]
            label = str(predator_instance.agent_id_nr)
            label_x = x_axis_x + i * (bar_width + offset_bars)
            label_y = x_axis_y + 10
            label_color = (255, 0, 0)  # red
            font = pygame.font.Font(None, 30)
            text = font.render(label, True, label_color)
            self.screen.blit(text, (label_x, label_y))
       # Draw tick labels prey on x-axis
        for i, prey_name in enumerate(self.prey_name_list):
            prey_instance = self.agent_name_to_instance_dict[prey_name]
            label = str(prey_instance.agent_id_nr)
            label_x = 310 + x_axis_x + i * (bar_width + offset_bars)
            label_y = x_axis_y + 10
            label_color = (0, 0, 255)  # blue
            font = pygame.font.Font(None, 30)
            text = font.render(label, True, label_color)
            self.screen.blit(text, (label_x, label_y))



        # Draw tick points on y-axis
        num_ticks = max_energy_value_chart + 1 
        tick_spacing = height // (num_ticks - 1)
        for i in range(num_ticks):
            tick_x = y_axis_x - 5
            tick_y = y_screenposition + height - i * tick_spacing
            tick_width = 10
            tick_height = 2
            tick_color = (0, 0, 0)  # black
            pygame.draw.rect(self.screen, tick_color, (tick_x, tick_y, tick_width, tick_height))

            # Draw tick labels every 5 ticks
            if i % 5 == 0:
                label = str(i)
                label_x = tick_x - 30
                label_y = tick_y - 5
                label_color = (0, 0, 0)  # black
                font = pygame.font.Font(None, 30)
                text = font.render(label, True, label_color)
                self.screen.blit(text, (label_x, label_y))

        # Draw prey bars
        data_prey = []
        for prey_name in self.prey_name_list:
            prey_instance = self.agent_name_to_instance_dict[prey_name]
            prey_energy = prey_instance.energy
            data_prey.append(prey_energy)
            #print(prey_name," has energy", round(prey_energy,1))
        x_screenposition = 750   
        y_screenposition = 50
        bar_width = 20
        offset_bars = 20
        height = 500
        for i, value in enumerate(data_prey):
            bar_height = (value / max_energy_value_chart) * height
            bar_x = x_screenposition + (self.width_energy_chart - (bar_width * len(data_prey))) // 2 + i * (bar_width+offset_bars)
            bar_y = y_screenposition + height - bar_height

            color = (0, 0, 255)  # blue

            pygame.draw.rect(self.screen, color, (bar_x, bar_y, bar_width, bar_height))

    def render(self):
        if self.render_mode is None:
            gymnasium.logger.warn(
                "You are calling render method without specifying any render mode."
            )
            return

        if self.screen is None:
            if self.render_mode == "human":
                pygame.display.init()
                self.screen = pygame.display.set_mode(
                    (self.cell_scale * self.x_grid_size +self.width_energy_chart, 
                     self.cell_scale * self.y_grid_size)
                )
                pygame.display.set_caption("PredPreyGrass")
            else:
                self.screen = pygame.Surface(
                    (self.cell_scale * self.x_grid_size, self.cell_scale * self.y_grid_size)
                )

        self.draw_grid_model()

        self.draw_prey_observations()
        self.draw_predator_observations()

        self.draw_grass_instances()
        self.draw_prey_instances()
        self.draw_predator_instances()

        self.draw_agent_instance_id_nrs()

        self.draw_white_canvas_energy_chart()

        self.draw_bar_chart_energy()


        observation = pygame.surfarray.pixels3d(self.screen)
        new_observation = np.copy(observation)
        del observation
        if self.render_mode == "human":
            pygame.event.pump()
            pygame.display.update()
            if self.save_image_steps:
                self.file_name+=1
                print(self.file_name+".png saved")
                directory= "./assets/images/"
                pygame.image.save(self.screen, directory+str(self.file_name)+".png")
        
        return (
            np.transpose(new_observation, axes=(1, 0, 2))
            if self.render_mode == "rgb_array"
            else None
        )


class raw_env(AECEnv, EzPickle):
    metadata = {
        "render_modes": ["human", "rgb_array"],
        "name": "predprey_35",
        "is_parallelizable": True,
        "render_fps": 5,
    }

    def __init__(self, *args, **kwargs):
        EzPickle.__init__(self, *args, **kwargs)

        self.render_mode = kwargs.get("render_mode")
        pygame.init()
        self.closed = False

        self.pred_prey_env = PredPrey(*args, **kwargs) #  this calls the code from PredPrey

        self.agents = self.pred_prey_env.agent_name_list 

        self.possible_agents = self.agents[:]

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.pred_prey_env._seed(seed=seed)
        self.steps = 0
        self.agents = self.possible_agents
             
        self.possible_agents = self.agents[:]
        self.agent_name_to_index_mapping = dict(zip(self.agents, list(range(self.num_agents))))
        self._agent_selector = agent_selector(self.agents)

        # spaces
        # self = raw_env
        self.action_spaces = dict(zip(self.agents, self.pred_prey_env.action_space)) # type: ignore
        self.observation_spaces = dict(zip(self.agents, self.pred_prey_env.observation_space)) # type: ignore
        self.steps = 0
        # this method "reset"
        self.rewards = dict(zip(self.agents, [(0) for _ in self.agents]))
        self._cumulative_rewards = dict(zip(self.agents, [(0) for _ in self.agents]))
        self.terminations = dict(zip(self.agents, [False for _ in self.agents]))
        self.truncations = dict(zip(self.agents, [False for _ in self.agents]))
        self.infos = dict(zip(self.agents, [{} for _ in self.agents]))
        self._agent_selector.reinit(self.agents)
        self.agent_selection = self._agent_selector.next()
        self.pred_prey_env.reset()  # this calls reset from PredPrey

    def close(self):
        if not self.closed:
            self.closed = True
            self.pred_prey_env.close()

    def render(self):
        if not self.closed:
            return self.pred_prey_env.render()

    def step(self, action):
        if (
            self.terminations[self.agent_selection]
            or self.truncations[self.agent_selection]
        ):
            self._was_dead_step(action)
            return
        agent = self.agent_selection
        agent_instance = self.pred_prey_env.agent_name_to_instance_dict[agent]
        self.pred_prey_env.step(
            action, agent_instance, self._agent_selector.is_last()
        )

        for k in self.terminations:
            if self.pred_prey_env.n_aec_cycles >= self.pred_prey_env.max_cycles:
                self.truncations[k] = True
            else:
                self.terminations[k] = \
                    self.pred_prey_env.is_no_grass or \
                    self.pred_prey_env.is_no_prey or \
                    self.pred_prey_env.is_no_predator
                
        for agent_name in self.agents:
        #for agent_name in self.pred_prey_env.agent_name_list:
        #for agent_name in self.possible_agents:
            self.rewards[agent_name] = self.pred_prey_env.agent_reward_dict[agent_name]
        self.steps += 1
        self._cumulative_rewards[self.agent_selection] = 0  # cannot be left out for proper rewards
        self.agent_selection = self._agent_selector.next()
        self._accumulate_rewards()  # cannot be left out for proper rewards
        if self.render_mode == "human":
            self.render()

    def observe(self, _agent_name):
        _agent_instance = self.pred_prey_env.agent_name_to_instance_dict[_agent_name]
        obs = self.pred_prey_env.observe(_agent_name)
        observation = np.swapaxes(obs, 2, 0) # type: ignore
        # return observation of only zeros if agent is not alive
        if _agent_instance.agent_type_nr==self.pred_prey_env.prey_type_nr and \
              not self.pred_prey_env.prey_alive_dict[_agent_name]:
            shape=observation.shape
            observation = np.zeros(shape)
        return observation
            
    def observation_space(self, agent: str):  # must remain
        return self.observation_spaces[agent]

    def action_space(self, agent: str):
        return self.action_spaces[agent]

    
