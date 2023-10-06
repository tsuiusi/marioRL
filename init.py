import torch
from torch import nn
from torchvision import transforms as T
from PIL import Image
import numpy as np
from pathlib import Path
from collections import deque
import random, datetime, os, copy
# import torchrl

# Gym is an OpenAI toolkit for RL
import gym
from gym.spaces import Box
from gym.wrappers import FrameStack

# NES Emulator for OpenAI Gym
from nes_py.wrappers import JoypadSpace

# Super Mario environment for OpenAI Gym
import gym_super_mario_bros

from tensordict import TensorDict
# from torchrl.data import TensorDictReplayBuffer, LazyMemmapStorage

if gym.__version__ < '0.26':
    env = gym_super_mario_bros.make("SuperMarioBros-1-1-v0", new_step_api=True)
else:
    env = gym_super_mario_bros.make("SuperMarioBros-1-1-v0", render_mode='rgb', apply_api_compatibility=True)

# Limiting actions to walk right and jump right
env = JoypadSpace(env, [["right"], ["right", "A"]])
env.reset()

next_state, reward, done, trunc, info = env.step(action=0)
print(f"{next_state.shape}, \n {reward}, \n {done}, \n{info}")

class SkipFrame(gym.Wrapper):
    def __init__(self, env, skip):
        # return only every skipth frame
        super().__init__(env)
        self._skip = skip
    
    def step(self, action):
        # Repeat action for no. frames skipped, sum reward)
        total_reward = 0.0
        for i in range(self._skip):
            obs, reward, done, trunk, info = self.env.step(action)
            total_reward += reward
            if done:
                break
        return obs, total_reward, done, trunk, info

class GrayScaleObservation(gym.ObservationWrapper):
    def __init__(self, env):
        super().__init__(env)
        obs_shape = self.observation_space.shape[:2]
        self.observation_space = Box(low=0, high=255, shape=obs_shape, dtype=np.uint8)
    
    def permute_orientation(self, observation):
        # transposing an array
        observation = np.transpose(observation, (2, 0, 1))
        observation = torch.tensor(observation.copy(), dtype=torch.float())
        return observation

    def observation(self, observation):
        observation = self.permute_observation(observation)
        transform = T.Grayscale
        observation = transform(observation)
        return observation

class ResizeObservation(gym.ObservationWrapper):
    def __init__(self, env, shape):
        super().__init__(env)
        if isinstance(shape, int):
            self.shape = (shape, shape)
        else:
            self.shape = tuple(shape)

        obs_shape = self.shape + self.observation_space.shape[2:]
        self.observation_space = Box(low=0, high=255, shape=obs_shape, dtype=np.uint8)
    def observation(self, observation):
        transforms = T.Compose(
                [T.Resize(self.shape), T.Normalize(0, 255)]
        )
        observation = transforms(observation).squeeze(0)
        return observation

# Applies filter onto frames
env = SkipFrame(env, skip=4)
env = GrayScaleObservation(env)
env = ResizeObservation(env, shape=84)

# Stacks the frames together
if gym.__version__ < '0.26':
    env = FrameStack(env, num_stack=4, new_step_api=True)
else:
    env = FrameStack(env, num_stack=4)

"""
Mario needs to be able to:
- Act according to action policy
- Retain experiences to update action policy (cache and recall)
- Learn/adapt action policy
"""

class Mario:
    def __init__(self, state_dim, action_dim, save_dir):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.save_dir = save_dir
        
        # Change this to see if i can use macbook gpus
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Mario's DNN to predict most optimal action/implemented in learn section
        self.net = MarioNet(self.state_dim, self.action_dim).float()
        self.net = self.net.to(device=self.device)

        self.exploration_rate = 1
        self.exploration_rate_decay = 0.99999975
        self.exploration_rate_min = 0.1
        self.curr_step = 0

        self.save_every = 5e5

        self.memory = TensorDictReplayBuffer(storage=LazyMemmapStorage(100000, device=torch.device("cpu")))
        self.batch_size = 32

        self.gamma = 0.9

    def act(self, state):
        # Choose greedy action (highest immediate reward without taking into account of long-term benefits)
        """
        Inputs: state(``LazyFrame``)
        Outputs: ``action_idx``(``int``) - an integer representing Mario's actions
        """
       # Explore 
       if np.random.rand() < self.exploration_rate:
            action_idx = np.random.randint(self.action_dim)
        
        # Exploit
        else:
            state = state[0].__array__() if isinstance(state, tuple) else state.__array__()
            state = torch.tensor(state, device=self.device).unsqueeze(0)
            action_values = self.net(state, model="online")
            action_idx = torch.argmax(action_values, axis=1).item()
        
        # Decrease exploration rate
        self.exploration_rate *= self.exploration_rate_decay
        self.exploration_rate = max(self.exploration_rate_min, self.exploration_rate)

        self.curr_step += 1
        return action_idx

    
    def cache(self, state, next_state, action, reward, done):
        # Save to memory
        def first_if_tuple(x):
            return x[0] if isinstance(x, tuple) else x

        state = first_if_tuple(state).__array__()
        next_state = first_if_tuple(next_state).__array__()

        state=  torch.tensor(state)
        next_state = torch.tensor(next_state)
        action = torch.tensor([action])
        reward = torch.tensor([reward])
        done = torch.tensor([done])

        # self.memory.append((state, next_state, action, reward, done))
        self.memory.add(TensorDict({"state": state, "next_state": next_state, "action": action, "reward": reward, "done": done}, batch_size=[]))


    def recall(self):
        # Recall from memory
        batch = self.memory.sample(self.batch_size).to(self.device)
        state, next_state, action, reward, done = (batch.get(key) for key in ("state", "next_state", "action", "reward", "done"))
        return state, next_state, action.squeeze(), reward.squeeze(), done.squeeze()

    def learn(self):
        # Update Q function (Q learning) with experiences
        def __init__(self, input_dim, output_dim):
            super().__init__()
            c, h, w = input_dim

            if h != 84:
                raise ValueError(f"Expected input height 84, got {h}")
            if w != 84:
                raise ValueError(f"Expected input width 84, got {w}")

            self.online = nn.Sequential(
                    nn.Conv2d(in_channels=c, out_channels=32, kernel_size=8, stride=4),
                    nn.ReLU(),
                    nn.Conv2d(in_channels=32, out_channels=64, kernel_size=4, stride=2),
                    nn.ReLU(), 
                    nn.Conv2d(in_channels=64, out_channels=64, kernel_size=3, stride=1),
                    nn.ReLU(),
                    nn.Flatten()
                    nn.Linear(3136, 512),
                    nn.ReLU(),
                    nn.Linear(512, output_dim),
                )

            self.target = copy.deepcopy(self.online)

            # Q_target parameters are frozen
            for p in self.target.parameters():
                p.requires_grad = False

        def forward(self, input, model):
            if model == "online":
                return self.online(input)
            elif model == "target":
                return self.target(input)

class Mario(Mario):
    def __init__(self, state_dim, action_dim, save_dir):
        super().__init__(state_dim, action_dim, save_dir)
        self.gamma = 0.9

    def td_estimate(self, state, action):
        current_Q = self.net(state, model="online") [
                np.arange(0, self.batch_size), action
        ] # Q_online(s, a)

        return current_Q

    @torch.no_grad()
    def td_target(self, reward, next_state, done):
        next_state_Q = self.net(next_state, model="online")
        best_action = torch.argmax(next_state_Q, axis=1)
        next_Q = self.net(next_state, model="target")[
                np.arange(0, self.batch_size), best_action
            ]
        return (reward + (1 - done.float()) * self.gamma * next_Q).float()

class Mario(Mario):
    def __init__(self, state_dim, action_dim, save_dir):
        super().__init__(state_dim, action_dim, save_dir)
        self.optimizer = torch.optim.Adam(self.net.parameters(), lr=0.00025)
        self.loss_fn = torch.nn.SmoothL1Loss()

    def update_Q_online(self, td_estimate, td_target):
        loss = self.loss_fn(td_estimate, td_target)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        return loss.item()

    def sync_Q_target(self):
        self.net.target.load_state_dict(self.net.online.state_dict())

