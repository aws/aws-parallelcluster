#
# Cookbook:: line
# Spec:: delete_from_list_missing_file
#
# Copyright:: 2017 Sous Chefs
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
#

require 'chefspec_helper'

describe 'spectest::delete_from_list_missing_file' do
  let(:chef_run) do
    chef_run = ChefSpec::SoloRunner.new(platform: 'ubuntu', version: '20.04', step_into: ['delete_from_list'])
    chef_run.converge(described_recipe)
  end

  it 'should throw error with a file not found message' do
    expect { chef_run }.to raise_error(RuntimeError).with_message(%r{File \/tmp\/nofilehere not found})
  end
end
