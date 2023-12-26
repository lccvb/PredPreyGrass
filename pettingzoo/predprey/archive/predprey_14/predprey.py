# noqa: D212, D415

import abc
from collections import defaultdict
from typing import Optional
import numpy as np
import pygame

import gymnasium
from gymnasium import spaces
from gymnasium.utils import seeding, EzPickle

from pettingzoo import AECEnv
from pettingzoo.utils import agent_selector
    
# Implements multi-agent controllers
class PredPreyPolicy(abc.ABC):
    @abc.abstractmethod
    def act(self, state: np.ndarray) -> int:
        raise NotImplementedError

class SingleActionPolicy(PredPreyPolicy):
    def __init__(self, a):
        self.action = a

    def act(self, state):
        return self.action

class RandomPolicy(PredPreyPolicy):
    # constructor
    def __init__(self, n_actions, rng):
        self.rng = rng
        self.n_actions = n_actions

    def set_rng(self, rng):
        self.rng = rng

    def act(self, state):
        return self.rng.integers(self.n_actions)

class DiscreteAgent():
    def __init__(
        self,
        x_size,
        y_size,
        agent_type_nr, # 0: wall, 1: prey, 2: grass 
        agent_id_nr,
        agent_id_name,
        observation_range=5,
        n_channels=3, # n channels is the number of observation channels
        flatten=False,
        moore_neighborhood=False
    ):
        
        self.x_size = x_size
        self.y_size = y_size
        self.agent_type_nr = agent_type_nr   # also channel number of agent 
        self.agent_id_name = agent_id_name   # string like "prey_1"
        self.agent_id_nr = agent_id_nr
        self.observation_range = observation_range
        self.observation_shape = (n_channels * observation_range**2 + 1,) if flatten else \
            (observation_range, observation_range, n_channels)
        self.moore_neighborhood = moore_neighborhood

        if moore_neighborhood:
            self.possible_actions = [
                0,  # move left/up
                1,  # move up
                2,  # move right/up
                3,  # move left
                4,  # stay
                5,  # move right
                6,  # move left/down 
                7,  # move down
                8,  # move right/down
            ]  
            self.motion_range = [[-1,-1], [0, -1], [1, -1], [-1, 0], [0, 0], [1, 0],[-1,1],[0,1],[-1,-1]]
        else:  #Von Neumann neighborhood
            self.possible_actions = [
                0,  # move up
                1,  # move left
                2,  # move right
                3,  # move down
                4,  # stay
            ]  
            self.motion_range = [[-1, 0], [1, 0], [0, 1], [0, -1], [0, 0]]
 
        self.n_actions_agent=len(self.possible_actions)   

        self.action_space_agent = spaces.Discrete(self.n_actions_agent) 

        self.position = np.zeros(2, dtype=np.int32)  # x and y position

        self.terminal = False
    
    def step(self, action):
        # returns new position of agent "self" given action "action"
        next_pos = np.zeros(2, dtype=np.int32) 
        next_pos[0], next_pos[1] = self.position[0], self.position[1]
        next_pos += self.motion_range[action]
        if self.terminal or not (0 <= next_pos[0] < self.x_size and 0 <= next_pos[1] < self.y_size):
            return self.position   # if dead or reached goal or if moved out of borders: dont move
        else:
            self.position = next_pos
            return self.position

    def set_position(self, x_size, y_size):
        self.position[0] = x_size
        self.position[1] = y_size

    def get_position(self):
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
        return agent_instance.get_position()

    def get_position_agent_index(self, agent_idx):
        return self.ally_agents_instance_list[agent_idx].get_position()

    def get_position_agent_name(self, agent_name):
        self.agent_name_to_instance_mapping[agent_name]
        return self.ally_agents_instance_list[agent_idx].get_position()

    def remove_agent(self, agent_idx):
        # idx is between zero and n_ally_agents
        self.ally_agents_instance_list.pop(agent_idx)
        self.n_ally_agents -= 1

    def remove_agent_instance(self, agent_instance):
        # idx is between zero and n_ally_agents
        self.ally_agents_instance_list.remove(agent_instance)
        self.n_ally_agents -= 1

    def get_global_state_ally_agents(self):
        global_state_ally_agents = self.global_state_ally_agents
        global_state_ally_agents.fill(0)
        for ally_agent_instance in self.ally_agents_instance_list:
            x, y = ally_agent_instance.get_position()
            global_state_ally_agents[x, y] += 1
        return global_state_ally_agents

class PredPrey:
    def __init__(
        self,
        x_size: int = 16,
        y_size: int = 16,
        max_cycles: int = 500,
        n_prey1: int = 4,
        n_prey2: int = 4,
        n_grasses: int = 10,
        max_observation_range: int =7,
        obs_range_prey1: int =7,
        obs_range_prey2: int =7,
        freeze_grasses: bool = False,
        catch_reward: float = 5.0,
        urgency_reward: float = -0.1,
        render_mode=None,
        moore_neighborhood_prey: bool = False,        
        moore_neighborhood_grasses: bool = False,
        grass_controller: Optional[PredPreyPolicy] = None,  #??? find out what it is doing
        prey_controller: Optional[PredPreyPolicy] = None,
        pixel_scale: int = 40

    ):
        #parameter init
        self.x_size = x_size
        self.y_size = y_size
        self.max_cycles = max_cycles
        self.n_grasses = n_grasses
        self.max_observation_range = max_observation_range
        self.obs_range_prey1 = obs_range_prey1        
        self.obs_range_prey2 = obs_range_prey2
        self.freeze_grasses = freeze_grasses
        self.catch_reward = catch_reward
        self.urgency_reward = urgency_reward
        self.render_mode = render_mode
        self.moore_neighborhood_prey = moore_neighborhood_prey
        self.moore_neighborhood_grasses = moore_neighborhood_grasses

        self._seed()
        self.agent_id_counter = 0
        self.n_prey1 = n_prey1
        self.n_prey2 = n_prey2
        self.num_agents = self.n_prey1 +self.n_prey2
        self.latest_done_state = [False for _ in range(self.num_agents)]

        # agent types
        self.agent_type_names = ["wall", "prey", "grass"]  # different types of agents 
        self.prey_type_nr = self.agent_type_names.index("prey")
        self.grass_type_nr = self.agent_type_names.index("grass")
        
        # lists of agents
        self.prey_instance_list = [] # list of all living prey
        self.prey1_instance_list = [] # list of all living prey1
        self.prey2_instance_list = [] # list of all living prey2
        self.prey1_name_list = [] # list of all living prey1
        self.prey2_name_list = [] # list of all living prey2
        self.grass_instance_list = [] # list of all living grasses
        self.agents = []

        self.agent_name_to_id_nr_mapping = dict()
        self.agent_name_to_instance_mapping = dict()

        self.n_actions_prey = 9 if self.moore_neighborhood_prey else 5
        self.n_actions_grasses = 9 if self.moore_neighborhood_grasses else 5 

        #controllers: still to find out how this is working
        if self.freeze_grasses:
            self.grass_controller = (
                # SingleActionPolicy(4) is NO move in both Von Nemann as well as Moore neighborhoods
                SingleActionPolicy(4)
                if grass_controller is None
                else grass_controller
            )
            self.prey_controller = (
                SingleActionPolicy(4)
                if prey_controller is None
                else prey_controller
            )
        else:
            
            self.grass_controller = (
                
                RandomPolicy(self.n_actions_grasses, self.np_random)
                if grass_controller is None
                else grass_controller
            )
            self.prey_controller = (
                RandomPolicy(self.n_actions_prey, self.np_random)
                if prey_controller is None
                else prey_controller
            )

        # maximum observation
        max_agents_overlap = max(self.num_agents, self.n_grasses)
        self.max_obs_offset = int((self.max_observation_range - 1) / 2) # remove later
        self.nr_observation_channels = len(self.agent_type_names)
        obs_space = spaces.Box(
            low=0,
            high=max_agents_overlap,
            shape=(self.max_observation_range, self.max_observation_range, self.nr_observation_channels),
            dtype=np.float32,
        )
        self.observation_space = [obs_space for _ in range(self.num_agents)]  # type: ignore
        self.obs_spaces_test = []
        # end observations


        act_space = spaces.Discrete(self.n_actions_prey)  #### MUST BE FLEXIBLE PER AGENT????
        self.action_space = [act_space for _ in range(self.num_agents)] # type: ignore


        self.screen = None
        self.pixel_scale = pixel_scale
        self.frames = 0

    def create_agents(
            self, 
            n_agents,
            agent_type_nr,
            observation_range, 
            randomizer, 
            flatten=False, 
            moore_neighborhood=True
            ):

        agent_instance_list = []

        agent_type_name = self.agent_type_names[agent_type_nr]
        for _ in range(n_agents): 
            agent_id_nr = self.agent_id_counter           
            agent_id_name = agent_type_name + "_" + str(agent_id_nr)
            self.agent_id_counter+=1
            # create the random position on the grid of the agent
            xinit, yinit = (randomizer.integers(0, self.x_size), randomizer.integers(0, self.y_size))      

            agent_instance = DiscreteAgent(
                self.x_size, 
                self.y_size, 
                agent_type_nr, 
                agent_id_nr,
                agent_id_name,
                observation_range=observation_range, 
                flatten=flatten, 
                moore_neighborhood=moore_neighborhood
            )
            #  updates lists en records
            self.agent_name_to_id_nr_mapping[agent_id_name] = agent_id_nr
            self.agent_name_to_instance_mapping[agent_id_name] = agent_instance
            self.agents.append(agent_id_name)
     
            agent_instance.set_position(xinit, yinit)
            agent_type_nr = 1
            agent_instance_list.append(agent_instance)
        return agent_instance_list

    def create_agent_name_list_from_instance_list(self, agent_instance_list):
        agent_name_list = []
        for agent in agent_instance_list:
            agent_name_list.append(agent.agent_id_name)
        return agent_name_list

    def reset(self):
        # empty agent lists
        self.agents = []
        self.prey_instance_list =[]
        self.prey1_instance_list =[]
        self.prey2_instance_list =[]
        self.prey1_name_list =[]
        self.prey2_name_list =[]
        self.grass_instance_list = []
        self.grass_name_list = []
        self.agent_id_counter = 0
        self.agent_name_to_id_nr_mapping = {}
        self.agent_name_to_instance_mapping = {}
        
        self.grasses_gone = np.array([False for i in range(self.n_grasses)])
        self.grasses_gone_dict = dict(zip(self.grass_name_list, [False for _ in self.grass_name_list]))
        
        self.model_state = np.zeros((self.nr_observation_channels, self.x_size, self.y_size), dtype=np.float32)
  
        #list agents consisting of prey1 agents
        self.prey1_instance_list = self.create_agents(
            self.n_prey1, self.prey_type_nr, self.obs_range_prey1, self.np_random, moore_neighborhood=False
        )
        self.prey1_name_list =  self.create_agent_name_list_from_instance_list(
            self.prey1_instance_list
        )
        #list agents consisting of prey2 agents
        self.prey2_instance_list = self.create_agents(
            self.n_prey2, self.prey_type_nr, self.obs_range_prey2, self.np_random, moore_neighborhood=False
        )
        self.prey2_name_list =  self.create_agent_name_list_from_instance_list(
            self.prey2_instance_list
        )
        self.grass_name_list =  self.create_agent_name_list_from_instance_list(
            self.grass_instance_list
        )

        #list prey (both prey1 and prey2)
        self.prey_instance_list = self.prey1_instance_list + self.prey2_instance_list 
        self.prey_name_list = self.prey1_name_list + self.prey2_name_list
        #print("self.prey_name_list ", self.prey_name_list)

        self.grass_instance_list = self.create_agents(
            # grass observation range is zero
            self.n_grasses, self.grass_type_nr, 0, self.np_random, moore_neighborhood=self.moore_neighborhood_grasses
        ) 

        self.prey_layer = AgentLayer(self.x_size, self.y_size, self.prey_instance_list)
        self.grass_layer = AgentLayer(self.x_size, self.y_size, self.grass_instance_list)
        # this is in method "reset"
        self.pred_prey_rewards = np.array([0.0 for _ in range(self.num_agents)])   
        self.pred_prey_rewards_dict = dict(zip(self.prey_name_list, [(0.0) for _ in self.prey_name_list]))
        #print("self.pred_prey_rewards_dict ",self.pred_prey_rewards_dict )
    

        self.latest_done_state = [False for _ in range(self.num_agents)]
        self.model_state[1] = self.prey_layer.get_global_state_ally_agents()
        self.model_state[2] = self.grass_layer.get_global_state_ally_agents()

        self.frames = 0

    def observation_space(self, agent):
        return self.observation_spaces[agent]

    def close(self):
        if self.screen is not None:
            pygame.quit()
            self.screen = None

    def _seed(self, seed=None):
        self.np_random, seed_ = seeding.np_random(seed)
        try:
            policies = [self.grass_controller, self.prey_controller]
            for policy in policies:
                try:
                    policy.set_rng(self.np_random)
                except AttributeError:
                    pass
        except AttributeError:
            pass

        return [seed_]

    def step(self, action, agent_instance, is_last):
        grass_layer = self.grass_layer  # updates only at end of cycle
        grass_controller = self.grass_controller

        # actual action application, change the prey layer
        self.prey_layer.move_agent_instance(agent_instance, action)

        # Update only the prey layer
        self.model_state[1] = self.prey_layer.get_global_state_ally_agents()
        #this is in method "step"
        self.pred_prey_rewards = np.array([0.0 for _ in range(self.num_agents)])

        if is_last:
            # Possibly change the grass layer
            #prey_instance_list_who_removes_grass = self.remove_grass()
            prey_who_remove = self.remove_agents()
            for grass_instance in self.grass_instance_list:
                # controller input should be an observation, but doesn't matter right now
                action = grass_controller.act(self.model_state)
                grass_layer.move_agent_instance(grass_instance, action)

            self.pred_prey_rewards += self.catch_reward * prey_who_remove
            self.pred_prey_rewards += self.urgency_reward
            #print("self.pred_prey_rewards ",self.pred_prey_rewards)
            self.frames = self.frames + 1

        # Update the remaining layers
        self.model_state[2] = self.grass_layer.get_global_state_ally_agents()

        if self.render_mode == "human":
            self.render()

    def draw_model_state(self):
        # -1 is building pixel flag
        x_len, y_len = (self.x_size, self.y_size)
        for x in range(x_len):
            for y in range(y_len):
                pos = pygame.Rect(
                    self.pixel_scale * x,
                    self.pixel_scale * y,
                    self.pixel_scale,
                    self.pixel_scale,
                )
                color = (255, 255, 255) # white background                
                #col = (0, 0, 0) # black background

                pygame.draw.rect(self.screen, color, pos)

    def draw_prey_observations(self):
        for prey_instance in self.prey_instance_list:
            position =  prey_instance.position 
            x = position[0]
            y = position[1]
            mask = int((self.max_observation_range - prey_instance.observation_range)/2)
            if mask == 0:
                patch = pygame.Surface(
                    (self.pixel_scale * self.max_observation_range, self.pixel_scale * self.max_observation_range)
                )
                patch.set_alpha(128)
                patch.fill((255, 152, 72))
                ofst = self.max_observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.pixel_scale * (x - ofst + 1 / 2),
                        self.pixel_scale * (y - ofst + 1 / 2),
                    ),
                )
            else:
                patch = pygame.Surface(
                    (self.pixel_scale * prey_instance.observation_range, self.pixel_scale * prey_instance.observation_range)
                )
                patch.set_alpha(128)
                patch.fill((255, 152, 72))
                ofst = prey_instance.observation_range / 2.0
                self.screen.blit(
                    patch,
                    (
                        self.pixel_scale * (x - ofst + 1 / 2),
                        self.pixel_scale * (y - ofst + 1 / 2),
                    ),
                )

    def draw_prey_instances(self):
        for prey_instance in self.prey_instance_list:
            position =  prey_instance.position 
            x = position[0]
            y = position[1]

            center = (
                int(self.pixel_scale * x + self.pixel_scale / 2),
                int(self.pixel_scale * y + self.pixel_scale / 2),
            )

            col = (0, 0, 255) # blue

            pygame.draw.circle(self.screen, col, center, int(self.pixel_scale / 3))

    def draw_grass_instances(self):
        for grass_instance in self.grass_instance_list:
            position =  grass_instance.position 
            x = position[0]
            y = position[1]

            center = (
                int(self.pixel_scale * x + self.pixel_scale / 2),
                int(self.pixel_scale * y + self.pixel_scale / 2),
            )

            col = (0, 128, 0) # green

            #col = (0, 0, 255) # blue

            pygame.draw.circle(self.screen, col, center, int(self.pixel_scale / 3))

    def draw_agent_instance_id_nrs(self):
        font = pygame.font.SysFont("Comic Sans MS", self.pixel_scale * 2 // 3)

        prey_positions = defaultdict(int)
        grass_positions = defaultdict(int)

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

        for x, y in prey_positions:
            (pos_x, pos_y) = (
                self.pixel_scale * x + self.pixel_scale // 2.4,
                self.pixel_scale * y + self.pixel_scale // 1.2,
            )

            prey_id_nr__text =str(prey_positions[(x, y)])

            prey_text = font.render(prey_id_nr__text, False, (255, 255, 0))

            self.screen.blit(prey_text, (pos_x, pos_y - self.pixel_scale // 2))

        for x, y in grass_positions:
            (pos_x, pos_y) = (
                self.pixel_scale * x + self.pixel_scale // 3.2,
                self.pixel_scale * y + self.pixel_scale // 1.2,
            )

            grass_id_nr__text =str(grass_positions[(x, y)])

            grass_text = font.render(grass_id_nr__text, False, (255, 255, 0))

            self.screen.blit(grass_text, (pos_x, pos_y - self.pixel_scale // 2))

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
                    (self.pixel_scale * self.x_size, self.pixel_scale * self.y_size)
                )
                pygame.display.set_caption("PreyGrass")
            else:
                self.screen = pygame.Surface(
                    (self.pixel_scale * self.x_size, self.pixel_scale * self.y_size)
                )

        self.draw_model_state()

        self.draw_prey_observations()

        self.draw_grass_instances()
        self.draw_prey_instances()
        self.draw_agent_instance_id_nrs()

        observation = pygame.surfarray.pixels3d(self.screen)
        new_observation = np.copy(observation)
        del observation
        if self.render_mode == "human":
            pygame.event.pump()
            pygame.display.update()
        return (
            np.transpose(new_observation, axes=(1, 0, 2))
            if self.render_mode == "rgb_array"
            else None
        )

    def save_image(self, file_name):
        self.render()
        capture = pygame.surfarray.array3d(self.screen)

        xl, xh = -self.max_obs_offset - 1, self.x_size + self.max_obs_offset + 1
        yl, yh = -self.max_obs_offset - 1, self.y_size + self.max_obs_offset + 1

        window = pygame.Rect(xl, yl, xh, yh)
        subcapture = capture.subsurface(window)

        pygame.image.save(subcapture, file_name)

    @property
    def is_terminal(self):
        # ev = self.grass_layer.get_global_state_ally_agents()  # grass positions
        # if np.sum(ev) == 0.0:
        if self.grass_layer.n_ally_layer_agents() == 0:
            return True
        return False

    def get_agent_instance_by_name(self, agent_id_name):
        return self.agent_name_to_instance_mapping[agent_id_name]

    def safely_observe_agent_name(self, agent_id_name):

        agent_instance = self.get_agent_instance_by_name(agent_id_name)

        xp, yp = agent_instance.position[0], agent_instance.position[1]

        # returns a flattened array of all the observations
        observation = np.zeros((self.nr_observation_channels, self.max_observation_range, self.max_observation_range), dtype=np.float32)
        observation[0].fill(1.0)  

        xlo, xhi, ylo, yhi, xolo, xohi, yolo, yohi = self.obs_clip(xp, yp)

        observation[0:3, xolo:xohi, yolo:yohi] = np.abs(self.model_state[0:3, xlo:xhi, ylo:yhi])
        
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
        else:
            return observation

    def obs_clip(self, x, y):
        xld = x - self.max_obs_offset
        xhd = x + self.max_obs_offset
        yld = y - self.max_obs_offset
        yhd = y + self.max_obs_offset
        xlo, xhi, ylo, yhi = (
            np.clip(xld, 0, self.x_size - 1),
            np.clip(xhd, 0, self.x_size - 1),
            np.clip(yld, 0, self.y_size - 1),
            np.clip(yhd, 0, self.y_size - 1),
        )
        xolo, yolo = abs(np.clip(xld, -self.max_obs_offset, 0)), abs(
            np.clip(yld, -self.max_obs_offset, 0)
        )
        xohi, yohi = xolo + (xhi - xlo), yolo + (yhi - ylo)
        return xlo, xhi + 1, ylo, yhi + 1, xolo, xohi + 1, yolo, yohi + 1

    def remove_agents1(self):
        removed_grass_names = []
        ai = 0
        rems = 0
        #prey_who_remove = np.zeros(self.num_agents, dtype=bool)
        #turned into dict
        prey_who_remove = dict(zip(self.prey_name_list, [False for _ in self.prey_name_list]))
        for grass_name in self.grass_name_list:
            if self.grasses_gone_dict[grass_name]:
                continue
            x, y = self.grass_layer.get_position_agent_instance(
                self.agent_name_to_instance_mapping[grass_name]
                )
            if self.model_state[1, x, y] > 0:   # prey on spot of grass
                # remove grass
                removed_grass_names.append(grass_name)
                self.grasses_gone_dict[grass_name] = True
                rems += 1
                for prey in self.prey_instance_list:  # identify all prey on the spot of the grass
                    xpp, ypp = self.prey_layer.get_position_agent_instance(prey)
                    if xpp == x and ypp == y:
                        prey_who_remove[prey.agent_id_name] = True
            ai += 1

        for grass_name in removed_grass_names:
            #self.grass_layer.remove_agent(ridx)
            self.grass_layer.remove_agent_instance(
                self.agent_name_to_instance_mapping[grass_name]
                )
        return prey_who_remove #returns named-key dict instead of indexed array

    def remove_agents(self): #works
        removed_grass = []
        ai = 0
        rems = 0
        prey_who_remove = np.zeros(self.num_agents, dtype=bool)
        #prey_instance_list_who_removes_grass = []
        for i in range(self.n_grasses):
            if self.grasses_gone[i]:
                continue
            x, y = self.grass_layer.get_position_agent_index(ai)
            if self.model_state[1, x, y] > 0:   # prey on spot of grass
                # remove grass
                removed_grass.append(ai - rems)
                self.grasses_gone[i] = True
                rems += 1
                for j in range(self.num_agents):  # identify all prey on the spot of the grass
                    xpp, ypp = self.prey_layer.get_position_agent_index(j)
                    if xpp == x and ypp == y:
                        prey_who_remove[j] = True
            ai += 1

        for ridx in removed_grass:
            self.grass_layer.remove_agent(ridx)
        return prey_who_remove

class raw_env(AECEnv, EzPickle):
    metadata = {
        "render_modes": ["human", "rgb_array"],
        "name": "predprey_14",
        "is_parallelizable": True,
        "render_fps": 5,
    }

    def __init__(self, *args, **kwargs):
        EzPickle.__init__(self, *args, **kwargs)

        self.pred_prey_env = PredPrey(*args, **kwargs) #  this calls the code from PredPrey
        self.render_mode = kwargs.get("render_mode")
        pygame.init()
        self.agents = ["prey_" + str(a) for a in range(self.pred_prey_env.num_agents)]  
        self.possible_agents = self.agents[:]
        self.closed = False

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.pred_prey_env._seed(seed=seed)
        self.steps = 0
        self.agents = ["prey_" + str(a) for a in range(self.pred_prey_env.num_agents)]
             
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
        #is_last_agent = self._agent_selector.is_last()
        agent_instance = self.get_agent_instance_by_name(agent)
        self.pred_prey_env.step(
            action, agent_instance, self._agent_selector.is_last()
        )

        for k in self.terminations:
            if self.pred_prey_env.frames >= self.pred_prey_env.max_cycles:
                self.truncations[k] = True
            else:
                self.terminations[k] = self.pred_prey_env.is_terminal
        for k in self.agents:
            #rewards is cumulative rewards of an agent
            self.rewards[k] = self.pred_prey_env.pred_prey_rewards[self.agent_name_to_index_mapping[k]]
        self.steps += 1
        #print("self.rewards ", self.rewards)

        # the agent which stepped last had its _cumulative_rewards accounted for
        # (because it was returned by last()), so the _cumulative_rewards for this
        # agent should start again at 0
        self._cumulative_rewards[self.agent_selection] = 0

        self.agent_selection = self._agent_selector.next()

        # Adds .rewards to ._cumulative_rewards
        self._accumulate_rewards()


        if self.render_mode == "human":
            self.render()

    def observe(self, agent_id_name):
        obs = self.pred_prey_env.safely_observe_agent_name(agent_id_name)
        observation = np.swapaxes(obs, 2, 0) # type: ignore
        return observation
    
    def observation_space(self, agent: str):  # must remain
        return self.observation_spaces[agent]

    def action_space(self, agent: str):
        return self.action_spaces[agent]

    def get_agent_instance_by_name(self, agent_id_name):
        return self.pred_prey_env.agent_name_to_instance_mapping[agent_id_name]
    
