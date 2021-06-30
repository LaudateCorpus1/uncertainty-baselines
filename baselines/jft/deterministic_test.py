# coding=utf-8
# Copyright 2021 The Uncertainty Baselines Authors.
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

"""Tests for the deterministic ViT on JFT-300M model script."""
import os
import pathlib
import shutil
import tempfile

from absl import flags
from absl import logging
from absl.testing import parameterized
import ml_collections
import tensorflow as tf
import tensorflow_datasets as tfds
import deterministic  # local file import

flags.adopt_module_key_flags(deterministic)
FLAGS = flags.FLAGS


def get_config():
  """Config for training a patch-transformer on JFT."""
  config = ml_collections.ConfigDict()

  # TODO(dusenberrymw): JFT + mocking is broken.
  # config.dataset = 'jft/entity:1.0.0'
  # config.val_split = 'test[:49511]'  # aka tiny_test/test[:5%] in task_adapt
  # config.train_split = 'train'  # task_adapt used train+validation so +64167
  # config.num_classes = 18291

  config.dataset = 'imagenet21k'
  config.val_split = 'full[:100]'
  config.train_split = 'full[100:200]'
  config.num_classes = 21843

  config.init_head_bias = -10.0

  config.trial = 0
  config.batch_size = 3
  config.total_steps = 1

  config.prefetch_to_device = 1

  pp_common = '|value_range(-1, 1)'
  pp_common += f'|onehot({config.num_classes})'
  pp_common += '|keep("image", "labels")'
  # TODO(dusenberrymw): Mocking doesn't seem to encode into jpeg format.
  # config.pp_train = 'decode_jpeg_and_inception_crop(224)|flip_lr' + pp_common
  config.pp_train = 'decode|resize_small(256)|central_crop(224)' + pp_common
  config.pp_eval = 'decode|resize_small(256)|central_crop(224)' + pp_common
  config.shuffle_buffer_size = 10

  config.log_training_steps = 1
  config.log_eval_steps = 1
  config.checkpoint_steps = 1
  config.keep_checkpoint_steps = 1

  # Model section
  config.model_name = 'resformer'
  config.model = ml_collections.ConfigDict()
  config.model.resnet = None
  config.model.patches = ml_collections.ConfigDict()
  config.model.patches.size = [16, 16]
  config.model.hidden_size = 2
  config.model.transformer = ml_collections.ConfigDict()
  config.model.transformer.attention_dropout_rate = 0.
  config.model.transformer.dropout_rate = 0.
  config.model.transformer.mlp_dim = 2
  config.model.transformer.num_heads = 1
  config.model.transformer.num_layers = 1
  config.model.classifier = 'token'  # Or 'gap'
  config.model.representation_size = 2

  # Optimizer section
  config.optim_name = 'Adam'
  config.optim = ml_collections.ConfigDict()
  config.optim.weight_decay = 0.1
  config.optim.beta1 = 0.9
  config.optim.beta2 = 0.999
  config.weight_decay = None  # No explicit weight decay

  config.lr = ml_collections.ConfigDict()
  config.lr.base = 0.001
  config.lr.warmup_steps = 2
  config.lr.decay_type = 'linear'
  config.lr.linear_end = 1e-5

  # Few-shot eval section
  config.fewshot = ml_collections.ConfigDict()
  config.fewshot.representation_layer = 'pre_logits'
  config.fewshot.log_steps = 1
  config.fewshot.datasets = {
      'pets': ('oxford_iiit_pet', 'train', 'test'),
      'imagenet': ('imagenet2012_subset/10pct', 'train', 'validation'),
  }
  config.fewshot.pp_train = 'decode|resize(256)|central_crop(224)|value_range(-1,1)'
  config.fewshot.pp_eval = 'decode|resize(256)|central_crop(224)|value_range(-1,1)'
  config.fewshot.shots = [1]
  config.fewshot.l2_regs = [2.0**-7]
  config.fewshot.walk_first = ('imagenet', config.fewshot.shots[0])

  return config


class DeterministicTest(parameterized.TestCase, tf.test.TestCase):

  def test_deterministic_script(self):
    # Set flags.
    FLAGS.xm_runlocal = True
    FLAGS.config = get_config()
    FLAGS.workdir = tempfile.mkdtemp(dir=self.get_temp_dir())

    # Go two directories up to the root of the UB directory.
    ub_root_dir = pathlib.Path(__file__).parents[2]
    data_dir = str(ub_root_dir) + '/.tfds/metadata'
    logging.info('data_dir contents: %s', os.listdir(data_dir))
    FLAGS.config.dataset_dir = data_dir

    # Check for any errors.
    with tfds.testing.mock_data(num_examples=100, data_dir=data_dir):
      train_loss, val_loss, fewshot_best_l2s = deterministic.main(None)

    # Check for reproducibility.
    self.assertAllClose(train_loss, 224.325)
    self.assertAllClose(val_loss, 269.692)
    self.assertAllClose(list(fewshot_best_l2s.values())[0], 0.0078125)

    # TODO(dusenberrymw): Check for ability to restart from previous checkpoint
    # (after failure, etc.).


if __name__ == '__main__':
  tf.test.main()