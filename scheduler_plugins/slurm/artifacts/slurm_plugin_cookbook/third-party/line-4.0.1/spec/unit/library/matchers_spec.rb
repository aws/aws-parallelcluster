#
# Cookbook:: line
# Spec:: matchers
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

describe 'test::matchers' do
  let(:chef_run) do
    chef_run = ChefSpec::SoloRunner.new(platform: 'ubuntu', version: '20.04')
    chef_run.converge(described_recipe)
  end

  it 'add_to_list' do
    expect(chef_run).to edit_add_to_list('Add to list 1')
  end

  it 'add_to_list is findable' do
    custom = chef_run.add_to_list('Add to list 1')
    expect(custom.to_s).to eq('add_to_list[Add to list 1]')
  end

  it 'append_if_no_line' do
    expect(chef_run).to edit_append_if_no_line('Operation')
  end

  it 'append_if_no_line is findable' do
    custom = chef_run.append_if_no_line('Operation')
    expect(custom.to_s).to eq('append_if_no_line[Operation]')
  end

  it 'delete_from_list' do
    expect(chef_run).to edit_delete_from_list('Delete Operation 1')
  end

  it 'delete_from_list is findable' do
    custom = chef_run.delete_from_list('Delete Operation 1')
    expect(custom.to_s).to eq('delete_from_list[Delete Operation 1]')
  end

  it 'delete_lines' do
    expect(chef_run).to edit_delete_lines('Operation 5')
  end

  it 'delete_lines is findable' do
    custom = chef_run.delete_lines('Operation 5')
    expect(custom.to_s).to eq('delete_lines[Operation 5]')
  end

  it 'replace_or_add' do
    expect(chef_run).to edit_replace_or_add('Operation 2')
  end

  it 'replace_or_add is findable' do
    custom = chef_run.replace_or_add('Operation 2')
    expect(custom.to_s).to eq('replace_or_add[Operation 2]')
  end
end
