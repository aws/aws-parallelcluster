#
# Copyright:: 2018 Sous Chefs
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

require 'rspec_helper'
include Line

describe 'options method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'Nil options input' do
    @filt.safe_default = true
    expect(@filt.options(nil, safe: [true, false])).to eq(safe: true)
  end

  it 'The most normal case should work' do
    expect(@filt.options({ safe: true }, safe: [true, false])).to eq(safe: true)
  end

  it 'longer list of allowed options' do
    expect(@filt.options({ safe: true }, safe: [true, false], extra: ['set1'])).to eq(safe: true)
  end

  it 'Should translate key strings to symbols' do
    expect(@filt.options({ 'safe' => true }, safe: [true, false])).to eq(safe: true)
  end

  it 'The option specified is not defined' do
    expect { @filt.options({ wrong: true }, safe: [true, false]) }.to raise_error(ArgumentError)
  end

  it 'The option value specified is not defined' do
    expect { @filt.options({ safe: 'wrong' }, safe: [true, false]) }.to raise_error(ArgumentError)
  end
end
