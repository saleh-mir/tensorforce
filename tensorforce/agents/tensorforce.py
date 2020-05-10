# Copyright 2020 Tensorforce Team. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from collections import OrderedDict
import os
from random import shuffle

import numpy as np

from tensorforce import TensorforceError, util
from tensorforce.agents import Agent
from tensorforce.core import ArrayDict
from tensorforce.core.models import TensorforceModel


class TensorforceAgent(Agent):
    """
    Tensorforce agent (specification key: `tensorforce`).

    Highly configurable agent and basis for a broad class of deep reinforcement learning agents,
    which act according to a policy parametrized by a neural network, leverage a memory module for
    periodic updates based on batches of experience, and optionally employ a baseline/critic/target
    policy for improved reward estimation.

    Args:
        states (specification): States specification
            (<span style="color:#C00000"><b>required</b></span>, better implicitly specified via
            `environment` argument for `Agent.create(...)`), arbitrarily nested dictionary of state
            descriptions (usually taken from `Environment.states()`) with the following attributes:
            <ul>
            <li><b>type</b> (<i>"bool" | "int" | "float"</i>) &ndash; state data type
            (<span style="color:#00C000"><b>default</b></span>: "float").</li>
            <li><b>shape</b> (<i>int | iter[int]</i>) &ndash; state shape
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>num_values</b> (<i>int > 0</i>) &ndash; number of discrete state values
            (<span style="color:#C00000"><b>required</b></span> for type "int").</li>
            <li><b>min_value/max_value</b> (<i>float</i>) &ndash; minimum/maximum state value
            (<span style="color:#00C000"><b>optional</b></span> for type "float").</li>
            </ul>
        actions (specification): Actions specification
            (<span style="color:#C00000"><b>required</b></span>, better implicitly specified via
            `environment` argument for `Agent.create(...)`), arbitrarily nested dictionary of
            action descriptions (usually taken from `Environment.actions()`) with the following
            attributes:
            <ul>
            <li><b>type</b> (<i>"bool" | "int" | "float"</i>) &ndash; action data type
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>shape</b> (<i>int > 0 | iter[int > 0]</i>) &ndash; action shape
            (<span style="color:#00C000"><b>default</b></span>: scalar).</li>
            <li><b>num_values</b> (<i>int > 0</i>) &ndash; number of discrete action values
            (<span style="color:#C00000"><b>required</b></span> for type "int").</li>
            <li><b>min_value/max_value</b> (<i>float</i>) &ndash; minimum/maximum action value
            (<span style="color:#00C000"><b>optional</b></span> for type "float").</li>
            </ul>
        max_episode_timesteps (int > 0): Upper bound for numer of timesteps per episode
            (<span style="color:#00C000"><b>default</b></span>: not given, better implicitly
            specified via `environment` argument for `Agent.create(...)`).

        policy (specification): Policy configuration, see [policies](../modules/policies.html)
            (<span style="color:#00C000"><b>default</b></span>: "default", action distributions
            parametrized by an automatically configured network).
        memory (int | specification): Memory configuration, see
            [memories](../modules/memories.html)
            (<span style="color:#00C000"><b>default</b></span>: replay memory with either given or
            minimum capacity).
        update (int | specification): Model update configuration with the following attributes
            (<span style="color:#C00000"><b>required</b>,
            <span style="color:#00C000"><b>default</b></span>: timesteps batch size</span>):
            <ul>
            <li><b>unit</b> (<i>"timesteps" | "episodes"</i>) &ndash; unit for update attributes
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>batch_size</b> (<i>parameter, int > 0</i>) &ndash; size of update batch in
            number of units (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>frequency</b> (<i>"never" | parameter, int > 0</i>) &ndash; frequency of
            updates (<span style="color:#00C000"><b>default</b></span>: batch_size).</li>
            <li><b>start</b> (<i>parameter, int >= batch_size</i>) &ndash; number of units
            before first update (<span style="color:#00C000"><b>default</b></span>: none).</li>
            </ul>
        optimizer (specification): Optimizer configuration, see
            [optimizers](../modules/optimizers.html)
            (<span style="color:#00C000"><b>default</b></span>: Adam optimizer).
        objective (specification): Optimization objective configuration, see
            [objectives](../modules/objectives.html)
            (<span style="color:#C00000"><b>required</b></span>).
        reward_estimation (specification): Reward estimation configuration with the following
            attributes (<span style="color:#C00000"><b>required</b></span>):
            <ul>
            <li><b>horizon</b> (<i>"episode" | parameter, int >= 0</i>) &ndash; Horizon of
            discounted-sum reward estimation
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>discount</b> (<i>parameter, 0.0 <= float <= 1.0</i>) &ndash; Discount factor for
            future rewards of discounted-sum reward estimation
            (<span style="color:#00C000"><b>default</b></span>: 1.0).</li>
            <li><b>estimate_horizon</b> (<i>false | "early" | "late"</i>) &ndash; Whether to include
            a baseline estimate of the horizon value as part of the return estimation, and if so,
            whether to compute the estimate early when experiences are stored to memory, or late
            when batches of experience are retrieved for optimization
            (<span style="color:#00C000"><b>default</b></span>: "late" if baseline_policy or
            baseline_objective are specified, else false).</li>
            <li><b>estimate_action_values</b> (<i>bool</i>) &ndash; Whether to estimate state-action
            instead of state values for the horizon estimate
            (<span style="color:#00C000"><b>default</b></span>: false).</li>
            <li><b>estimate_terminals</b> (<i>bool</i>) &ndash; Whether to estimate the value of
            terminal horizon states
            (<span style="color:#00C000"><b>default</b></span>: false).</li>
            <li><b>estimate_advantage</b> (<i>bool</i>) &ndash; Whether to estimate the advantage
            instead of the return by subtracting the baseline value estimate from the return
            (<span style="color:#00C000"><b>default</b></span>: false, unless baseline_policy is
            specified but baseline_objective/optimizer are not).</li>
            </ul>

        baseline_policy (specification): Baseline policy configuration, main policy will be used as
            baseline if none
            (<span style="color:#00C000"><b>default</b></span>: none).
        baseline_optimizer (specification | parameter, float > 0.0): Baseline optimizer
            configuration, see [optimizers](../modules/optimizers.html), main optimizer will be used
            for baseline if none, a float implies none and specifies a custom weight for the
            baseline loss
            (<span style="color:#00C000"><b>default</b></span>: none).
        baseline_objective (specification): Baseline optimization objective configuration, see
            [objectives](../modules/objectives.html), required if baseline optimizer is specified,
            main objective will be used for baseline if baseline objective and optimizer are not
            specified
            (<span style="color:#00C000"><b>default</b></span>: none).

        preprocessing (dict[specification]): Preprocessing as layer or list of layers, see
            [preprocessing](../modules/preprocessing.html), specified per state-name or -type, and
            for reward/return/advantage
            (<span style="color:#00C000"><b>default</b></span>: none).

        exploration (parameter | dict[parameter], float >= 0.0): Exploration, global or per
            action-name or -type, defined as the probability for uniformly random output in case of
            `bool` and `int` actions, and the standard deviation of Gaussian noise added to every
            output in case of `float` actions
            (<span style="color:#00C000"><b>default</b></span>: 0.0).
        variable_noise (parameter, float >= 0.0): Standard deviation of Gaussian noise added to all
            trainable float variables (<span style="color:#00C000"><b>default</b></span>: 0.0).

        l2_regularization (parameter, float >= 0.0): Scalar controlling L2 regularization
            (<span style="color:#00C000"><b>default</b></span>:
            0.0).
        entropy_regularization (parameter, float >= 0.0): Scalar controlling entropy
            regularization, to discourage the policy distribution being too "certain" / spiked
            (<span style="color:#00C000"><b>default</b></span>: 0.0).

        name (string): Agent name, used e.g. for TensorFlow scopes and saver default filename
            (<span style="color:#00C000"><b>default</b></span>: "agent").
        device (string): Device name
            (<span style="color:#00C000"><b>default</b></span>: TensorFlow default).
        parallel_interactions (int > 0): Maximum number of parallel interactions to support,
            for instance, to enable multiple parallel episodes, environments or (centrally
            controlled) agents within an environment
            (<span style="color:#00C000"><b>default</b></span>: 1).
        config (specification): Various additional configuration options:
            buffer_observe (int > 0): Maximum number of timesteps within an episode to buffer before
                executing internal observe operations, to reduce calls to TensorFlow for improved
                performance
                (<span style="color:#00C000"><b>default</b></span>: simple rules to infer maximum
                number which can be buffered without affecting performance).
            seed (int): Random seed to set for Python, NumPy (both set globally!) and TensorFlow,
                environment seed may have to be set separately for fully deterministic execution
                (<span style="color:#00C000"><b>default</b></span>: none).
        saver (specification): TensorFlow saver configuration for periodic implicit saving, as
            alternative to explicit saving via agent.save(...), with the following attributes
            (<span style="color:#00C000"><b>default</b></span>: no saver):
            <ul>
            <li><b>directory</b> (<i>path</i>) &ndash; saver directory
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>filename</b> (<i>string</i>) &ndash; model filename
            (<span style="color:#00C000"><b>default</b></span>: agent name).</li>
            <li><b>frequency</b> (<i>int > 0</i>) &ndash; how frequently in seconds to save the
            model (<span style="color:#00C000"><b>default</b></span>: 600 seconds).</li>
            <li><b>load</b> (<i>bool | str</i>) &ndash; whether to load the existing model, or
            which model filename to load
            (<span style="color:#00C000"><b>default</b></span>: true).</li>
            </ul>
            <li><b>max-checkpoints</b> (<i>int > 0</i>) &ndash; maximum number of checkpoints to
            keep (<span style="color:#00C000"><b>default</b></span>: 5).</li>
        summarizer (specification): TensorBoard summarizer configuration with the following
            attributes (<span style="color:#00C000"><b>default</b></span>: no summarizer):
            <ul>
            <li><b>directory</b> (<i>path</i>) &ndash; summarizer directory
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>frequency</b> (<i>int > 0, dict[int > 0]</i>) &ndash; how frequently in
            timesteps to record summaries for act-summaries if specified globally
            (<span style="color:#00C000"><b>default</b></span>: always),
            otherwise specified for act-summaries via "act" in timesteps, for
            observe/experience-summaries via "observe"/"experience" in episodes, and for
            update/variables-summaries via "update"/"variables" in updates
            (<span style="color:#00C000"><b>default</b></span>: never).</li>
            <li><b>flush</b> (<i>int > 0</i>) &ndash; how frequently in seconds to flush the
            summary writer (<span style="color:#00C000"><b>default</b></span>: 10).</li>
            <li><b>max-summaries</b> (<i>int > 0</i>) &ndash; maximum number of summaries to keep
            (<span style="color:#00C000"><b>default</b></span>: 5).</li>
            <li><b>custom</b> (<i>dict[spec]</i>) &ndash; custom summaries which are recorded via
            `agent.summarize(...)`, specification with either type "scalar", type "histogram" with
            optional "buckets", type "image" with optional "max_outputs"
            (<span style="color:#00C000"><b>default</b></span>: 3), or type "audio"
            (<span style="color:#00C000"><b>default</b></span>: no custom summaries).</li>
            <li><b>labels</b> (<i>"all" | iter[string]</i>) &ndash; all excluding "*-histogram"
            labels, or list of summaries to record, from the following labels
            (<span style="color:#00C000"><b>default</b></span>: only "graph"):</li>
            <li>"distributions" or "bernoulli", "categorical", "gaussian", "beta":
            distribution-specific parameters</li>
            <li>"dropout": dropout zero fraction</li>
            <li>"entropies" or "entropy", "action-entropies": entropy of policy
            distribution(s)</li>
            <li>"graph": graph summary</li>
            <li>"kl-divergences" or "kl-divergence", "action-kl-divergences": KL-divergence of
            previous and updated polidcy distribution(s)</li>
            <li>"losses" or "loss", "objective-loss", "regularization-loss", "baseline-loss",
            "baseline-objective-loss", "baseline-regularization-loss": loss scalars</li>
            <li>"parameters": parameter scalars</li>
            <li>"relu": ReLU activation zero fraction</li>
            <li>"rewards" or "episode-reward", "reward", "return", "advantage": reward scalar</li>
            <li>"update-norm": update norm</li>
            <li>"updates": update mean and variance scalars</li>
            <li>"updates-histogram": update histograms</li>
            <li>"variables": variable mean and variance scalars</li>
            <li>"variables-histogram": variable histograms</li>
            </ul>
        recorder (specification): Experience traces recorder configuration, currently not including
            internal states, with the following attributes
            (<span style="color:#00C000"><b>default</b></span>: no recorder):
            <ul>
            <li><b>directory</b> (<i>path</i>) &ndash; recorder directory
            (<span style="color:#C00000"><b>required</b></span>).</li>
            <li><b>frequency</b> (<i>int > 0</i>) &ndash; how frequently in episodes to record
            traces (<span style="color:#00C000"><b>default</b></span>: every episode).</li>
            <li><b>start</b> (<i>int >= 0</i>) &ndash; how many episodes to skip before starting to
            record traces (<span style="color:#00C000"><b>default</b></span>: 0).</li>
            <li><b>max-traces</b> (<i>int > 0</i>) &ndash; maximum number of traces to keep
            (<span style="color:#00C000"><b>default</b></span>: all).</li>
    """

    def __init__(
        # Required
        self, states, actions, update, objective, reward_estimation,
        # Environment
        max_episode_timesteps=None,
        # Agent
        policy='default', memory=None, optimizer='adam',
        # Baseline
        baseline_policy=None, baseline_optimizer=None, baseline_objective=None,
        # Preprocessing
        preprocessing=None,
        # Exploration
        exploration=0.0, variable_noise=0.0,
        # Regularization
        l2_regularization=0.0, entropy_regularization=0.0,
        # TensorFlow etc
        name='agent', device=None, parallel_interactions=1, config=None, saver=None,
        summarizer=None, recorder=None
    ):
        if not hasattr(self, 'spec'):
            self.spec = OrderedDict(
                agent='tensorforce',
                # Environment
                states=states, actions=actions, max_episode_timesteps=max_episode_timesteps,
                # Agent
                policy=policy, memory=memory, update=update, optimizer=optimizer,
                objective=objective, reward_estimation=reward_estimation,
                # Baseline
                baseline_policy=baseline_policy, baseline_optimizer=baseline_optimizer,
                baseline_objective=baseline_objective,
                # Preprocessing
                preprocessing=preprocessing,
                # Exploration
                exploration=exploration, variable_noise=variable_noise,
                # Regularization
                l2_regularization=l2_regularization, entropy_regularization=entropy_regularization,
                # TensorFlow etc
                name=name, device=device, parallel_interactions=parallel_interactions,
                config=config, saver=saver, summarizer=summarizer, recorder=recorder
            )

        if isinstance(update, int):
            update = dict(unit='timesteps', batch_size=update)

        if config is None:
            config = dict()
        else:
            config = dict(config)

        # TODO: should this change if summarizer is specified?
        if parallel_interactions > 1:
            if 'buffer_observe' not in config:
                if max_episode_timesteps is None:
                    raise TensorforceError.required(
                        name='Agent', argument='max_episode_timesteps',
                        condition='parallel_interactions > 1'
                    )
                config['buffer_observe'] = max_episode_timesteps
            elif config['buffer_observe'] < max_episode_timesteps:
                raise TensorforceError.value(
                    name='Agent', argument='config[buffer_observe]',
                    hint='< max_episode_timesteps', condition='parallel_interactions > 1'
                )

        elif update['unit'] == 'timesteps':
            if 'buffer_observe' not in config:
                if isinstance(update['batch_size'], int):
                    config['buffer_observe'] = update['batch_size']
                else:
                    config['buffer_observe'] = 1
            elif config['buffer_observe'] > update['batch_size']:
                raise TensorforceError.value(
                    name='Agent', argument='config[buffer_observe]',
                    hint='> update[batch_size]', condition='update[unit] = "timesteps"'
                )

        elif update['unit'] == 'episodes':
            if 'buffer_observe' not in config:
                if max_episode_timesteps is None:
                    config['buffer_observe'] = 1000
                else:
                    config['buffer_observe'] = max_episode_timesteps

        reward_estimation = dict(reward_estimation)
        if reward_estimation['horizon'] == 'episode':
            if max_episode_timesteps is None:
                raise TensorforceError.required(
                    name='Agent', argument='max_episode_timesteps',
                    condition='reward_estimation[horizon] = "episode"'
                )
            reward_estimation['horizon'] = max_episode_timesteps

        super().__init__(
            states=states, actions=actions, max_episode_timesteps=max_episode_timesteps,
            parallel_interactions=parallel_interactions, config=config, recorder=recorder
        )

        self.model = TensorforceModel(
            # Model
            states=self.states_spec, actions=self.actions_spec, preprocessing=preprocessing,
            exploration=exploration, variable_noise=variable_noise,
            l2_regularization=l2_regularization, name=name, device=device,
            parallel_interactions=self.parallel_interactions, config=self.config, saver=saver,
            summarizer=summarizer,
            # TensorforceModel
            policy=policy, memory=memory, update=update, optimizer=optimizer, objective=objective,
            reward_estimation=reward_estimation, baseline_policy=baseline_policy,
            baseline_optimizer=baseline_optimizer, baseline_objective=baseline_objective,
            entropy_regularization=entropy_regularization,
            max_episode_timesteps=self.max_episode_timesteps
        )

        self.experience_size = self.model.estimator.capacity

    def experience(self, states, actions, terminal, reward, internals=None):
        """
        Feed experience traces.

        Args:
            states (dict[array[state]]): Dictionary containing arrays of states
                (<span style="color:#C00000"><b>required</b></span>).
            actions (dict[array[action]]): Dictionary containing arrays of actions
                (<span style="color:#C00000"><b>required</b></span>).
            terminal (array[bool]): Array of terminals
                (<span style="color:#C00000"><b>required</b></span>).
            reward (array[float]): Array of rewards
                (<span style="color:#C00000"><b>required</b></span>).
            internals (dict[state]): Dictionary containing arrays of internal agent states
                (<span style="color:#C00000"><b>required</b></span> if agent has internal states).
        """
        if not (self.buffer_indices == 0).all():
            raise TensorforceError(message="Calling agent.experience is not possible mid-episode.")

        # Process states input and infer batching structure
        states, batched, num_instances, is_iter_of_dicts, input_type = self._process_states_input(
            states=states, function_name='Agent.experience'
        )

        if is_iter_of_dicts:
            # Input structure iter[dict[input]]

            # Internals
            if internals is None:
                internals = ArrayDict()
            elif not isinstance(internals, (tuple, list)):
                raise TensorforceError.type(
                    name='Agent.experience', argument='internals', dtype=type(internals),
                    hint='is not tuple/list'
                )
            else:
                internals = [ArrayDict(internal) for internal in internals]
                internals = internals[0].fmap(
                    function=(lambda *xs: np.stack(xs, axis=0)), zip_values=internals[1:]
                )

            # Actions
            if self.single_action and isinstance(actions, np.ndarray):
                actions = ArrayDict(action=actions)
            elif not isinstance(actions, (tuple, list)):
                raise TensorforceError.type(
                    name='Agent.experience', argument='actions', dtype=type(actions),
                    hint='is not tuple/list'
                )
            elif self.single_action and not isinstance(actions[0], dict):
                actions = ArrayDict(action=actions)
            else:
                actions = [ArrayDict(action) for action in actions]
                actions = internals[0].fmap(
                    function=(lambda *xs: np.stack(xs, axis=0)), zip_values=actions[1:]
                )

        else:
            # Input structure dict[iter[input]]

            # Internals
            if internals is None:
                internals = ArrayDict()
            elif not isinstance(internals, dict):
                raise TensorforceError.type(
                    name='Agent.experience', argument='internals', dtype=type(internals),
                    hint='is not dict'
                )
            else:
                internals = ArrayDict(internals)

            # Actions
            if self.single_action and not isinstance(actions, dict):
                actions = dict(action=actions)
            elif not isinstance(actions, dict):
                raise TensorforceError.type(
                    name='Agent.experience', argument='actions', dtype=type(actions),
                    hint='is not dict'
                )
            actions = ArrayDict(actions)

        # Expand inputs if not batched
        if not batched:
            internals = internals.fmap(function=(lambda x: np.expand_dims(x, axis=0)))
            actions = actions.fmap(function=(lambda x: np.expand_dims(x, axis=0)))
            terminal = np.asarray([terminal])
            reward = np.asarray([reward])
        else:
            terminal = np.asarray(terminal)
            reward = np.asarray(reward)

        # Check number of inputs
        for name, internal in internals.items():
            if internal.shape[0] != num_instances:
                raise TensorforceError.value(
                    name='Agent.experience', argument='len(internals[{}])'.format(name),
                    value=internal.shape[0], hint='!= len(states)'
                )
        for name, action in actions.items():
            if action.shape[0] != num_instances:
                raise TensorforceError.value(
                    name='Agent.experience', argument='len(actions[{}])'.format(name),
                    value=action.shape[0], hint='!= len(states)'
                )
        if terminal.shape[0] != num_instances:
            raise TensorforceError.value(
                name='Agent.experience', argument='len(terminal)'.format(name),
                value=terminal.shape[0], hint='!= len(states)'
            )
        if reward.shape[0] != num_instances:
            raise TensorforceError.value(
                name='Agent.experience', argument='len(reward)'.format(name),
                value=reward.shape[0], hint='!= len(states)'
            )

        def function(name, spec):
            auxiliary = ArrayDict()
            if self.config.enable_int_action_masking and spec.type == 'int' and \
                    spec.num_values is not None:
                # Mask, either part of states or default all true
                auxiliary['mask'] = states.pop(name + '_mask', np.ones(
                    shape=(num_instances,) + spec.shape + (spec.num_values,), dtype=spec.np_type()
                ))
            return auxiliary

        auxiliaries = self.actions_spec.fmap(function=function, cls=ArrayDict, with_names=True)

        # Convert terminal to int if necessary
        if terminal.dtype is util.np_dtype(dtype='bool'):
            zeros = np.zeros_like(terminal, dtype=util.np_dtype(dtype='int'))
            ones = np.ones_like(terminal, dtype=util.np_dtype(dtype='int'))
            terminal = np.where(terminal, ones, zeros)

        # Batch experiences split into episodes and at most size buffer_observe
        last = 0
        for index in range(1, len(terminal) + 1):
            if terminal[index - 1] == 0 and index - last < self.experience_size:
                continue

            # Include terminal in batch if possible
            if index < len(terminal) and terminal[index - 1] == 0 and terminal[index] > 0 and \
                    index - last < self.experience_size:
                index += 1

            function = (lambda x: x[last: index])
            states_batch = states.fmap(function=function)
            internals_batch = internals.fmap(function=function)
            auxiliaries_batch = auxiliaries.fmap(function=function)
            actions_batch = actions.fmap(function=function)
            terminal_batch = function(terminal)
            reward_batch = function(reward)
            last = index

            # Inputs to tensors
            states_batch = self.states_spec.to_tensor(value=states_batch, batched=True)
            internals_batch = self.internals_spec.to_tensor(value=internals_batch, batched=True)
            auxiliaries_batch = self.auxiliaries_spec.to_tensor(
                value=auxiliaries_batch, batched=True
            )
            actions_batch = self.actions_spec.to_tensor(value=actions_batch, batched=True)
            terminal_batch = self.terminal_spec.to_tensor(value=terminal_batch, batched=True)
            reward_batch = self.reward_spec.to_tensor(value=reward_batch, batched=True)

            # Model.experience()
            timesteps, episodes, updates = self.model.experience(
                states=states_batch, internals=internals_batch, auxiliaries=auxiliaries_batch,
                actions=actions_batch, terminal=terminal_batch, reward=reward_batch
            )
            self.timesteps = timesteps.numpy().item()
            self.episodes = episodes.numpy().item()
            self.updates = updates.numpy().item()

    def update(self, query=None, **kwargs):
        """
        Perform an update.
        """
        timesteps, episodes, updates = self.model.update()
        self.timesteps = timesteps.numpy().item()
        self.episodes = episodes.numpy().item()
        self.updates = updates.numpy().item()

    def pretrain(self, directory, num_iterations, num_traces=1, num_updates=1):
        """
        Pretrain from experience traces.

        Args:
            directory (path): Directory with experience traces, e.g. obtained via recorder; episode
                length has to be consistent with agent configuration
                (<span style="color:#C00000"><b>required</b></span>).
            num_iterations (int > 0): Number of iterations consisting of loading new traces and
                performing multiple updates
                (<span style="color:#C00000"><b>required</b></span>).
            num_traces (int > 0): Number of traces to load per iteration; has to at least satisfy
                the update batch size
                (<span style="color:#00C000"><b>default</b></span>: 1).
            num_updates (int > 0): Number of updates per iteration
                (<span style="color:#00C000"><b>default</b></span>: 1).
        """
        if not os.path.isdir(directory):
            raise TensorforceError.value(
                name='agent.pretrain', argument='directory', value=directory
            )
        files = sorted(
            os.path.join(directory, f) for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f)) and f.startswith('trace-')
        )
        indices = list(range(len(files)))

        for _ in range(num_iterations):
            shuffle(indices)
            if num_traces is None:
                selection = indices
            else:
                selection = indices[:num_traces]

            # function = (lambda x: list())
            # values = ListDict()
            # values['states'] = self.states_spec.fmap(function=function, cls=ListDict)
            # values['auxiliaries'] = self.auxiliaries_spec.fmap(function=function, cls=ListDict)
            # values['actions'] = self.actions_spec.fmap(function=function, cls=ListDict)
            # values['terminal'] = list()
            # values['reward'] = list()
            batch = None
            for index in selection:
                trace = ArrayDict(np.load(files[index]))
                if batch is None:
                    batch = trace
                else:
                    batch = batch.fmap(
                        function=(lambda x, y: np.concatenate([x, y], axis=0)), zip_values=(trace,)
                    )

            for name, value in batch.pop('auxiliaries').items():
                assert name.endswith('/mask')
                batch['states'][name[:-5] + '_mask'] = value

            # values = values.fmap(function=np.concatenate, cls=ArrayDict)

            self.experience(**batch)
            for _ in range(num_updates):
                self.update()
            # TODO: self.obliviate()
