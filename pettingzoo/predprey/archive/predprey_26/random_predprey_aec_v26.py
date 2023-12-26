from predprey import raw_env
from pettingzoo.utils import agent_selector
import numpy as np


env_kwargs = dict(
    render_mode="human", 
    max_cycles=10000, 
    x_size=16, 
    y_size=16, 
    n_predator=10,
    n_prey=3,
    n_grass=30,
    max_observation_range=7,     
    obs_range_predator=3,     
    obs_range_prey=7,
    freeze_grass=True, 
    moore_neighborhood_prey=False,
    pixel_scale=40
)

num_games = 10
if num_games > 1:
    env_kwargs["render_mode"]="None"

raw_env = raw_env(**env_kwargs) 

def average(rewards):
    N = len(rewards)
    avg_rewards = sum(rewards) / N
    return avg_rewards

def std_dev(rewards, avg_reward):
    N = len(rewards.values())
    variance_rewards = 0
    for _agent in rewards:
        variance_rewards += pow(rewards[_agent]-avg_reward,2)
    variance_rewards = 1/(N-1)*variance_rewards
    std_rewards = pow(variance_rewards,0.5)
    return std_rewards

avg_rewards = [0 for _ in range(num_games)]
avg_cycles = [0 for _ in range(num_games)]
std_rewards = [0 for _ in range(num_games)]

agent_selector = agent_selector(agent_order=raw_env.agents)

for i in range(num_games):
    raw_env.reset(seed=i)
    agent_selector.reset()
    cumulative_rewards = {agent: 0.0 for agent in raw_env.possible_agents}
    n_aec_cycles = 0
    for agent in raw_env.agent_iter():
        
        observation, reward, termination, truncation, info = raw_env.last()
        """        
        if agent=="prey_10" or agent=="prey_11" or agent=="prey_12":
            print()
            #print(raw_env.pred_prey_env.prey_name_list)
            print()
            print(agent)
            #print("shape")
            #print(np.shape(observation))
            print("=================")
            print("Walls")
            print(np.transpose(np.transpose(observation)[0]))
            print()
            print(agent)
            print(np.transpose(np.transpose(observation)[1]))
            print()
            print("Grass")
            print(np.transpose(np.transpose(observation)[2]))
            print()
            print("Predators")
            print(np.transpose(np.transpose(observation)[3]))
            print("===================")
        """
        
        cumulative_rewards[agent] += reward
        if termination or truncation:
            action = None
        else:
            action = raw_env.action_space(agent).sample()
        raw_env.step(action)
        if agent_selector.is_last(): # called at end of cycle
            n_aec_cycles += 1
            #print("agents list",raw_env.agents)
            #print("pred+prey agents list",raw_env.pred_prey_env.agent_name_list)

            #print({key : round(cumulative_rewards[key], 2) for key in cumulative_rewards}) # DON'T REMOVE

        agent_selector.next()   # called at end of cycle

    avg_rewards[i]= average(cumulative_rewards.values()) # type: ignore
    avg_cycles[i]= n_aec_cycles
    std_rewards[i]= std_dev(cumulative_rewards, avg_rewards[i])
    print(f"Cycles = {n_aec_cycles}", f"Avg = {round(avg_rewards[i],1)}", 
          f"Std = {round(std_rewards[i],1)}",end=" ")
    print()
raw_env.close()
print(f"Average of Avg = {round(average(avg_rewards),1)}")
print(f"Average of Cycles = {round(average(avg_cycles),1)}")
