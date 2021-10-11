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

describe 'expand method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'An empty array should retun an empty array' do
    expect(@filt.expand([])).to eq([])
  end

  it 'An array with just lines should return the same array' do
    expect(@filt.expand([1, 2, 3, 4])).to eq([1, 2, 3, 4])
  end

  it 'An array with a replacement line should add lines at the replacement point - first, before' do
    expect(@filt.expand([Replacement.new('1', %w(a b c), :before), '2', '3', '4'])).to eq(%w(a b c 1 2 3 4))
  end

  it 'An array with a replacement line should add lines at the replacement point - first, after' do
    expect(@filt.expand([Replacement.new('1', %w(a b c), :after), '2', '3', '4'])).to eq(%w(1 a b c 2 3 4))
  end

  it 'An array with a replacement line should add lines at the replacement point - first, replace' do
    expect(@filt.expand([Replacement.new('1', %w(a b c), :replace), '2', '3', '4'])).to eq(%w(a b c 2 3 4))
  end

  it 'An array with a replacement line should add lines at the replacement point - last, before' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :before)])).to eq(%w(1 2 3 a b c 4))
  end

  it 'An array with a replacement line should add lines at the replacement point - last, after' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :after)])).to eq(%w(1 2 3 4 a b c))
  end

  it 'An array with a replacement line should add lines at the replacement point - last, replace' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :replace)])).to eq(%w(1 2 3 a b c))
  end

  it 'An array with a replacement line should add lines at the replacement point - middle, before' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :before), '5'])).to eq(%w(1 2 3 a b c 4 5))
  end

  it 'An array with a replacement line should add lines at the replacement point - middle, after' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :after), '5'])).to eq(%w(1 2 3 4 a b c 5))
  end

  it 'An array with a replacement line should add lines at the replacement point - middle, replace' do
    expect(@filt.expand(['1', '2', '3', Replacement.new('4', %w(a b c), :replace), '5'])).to eq(%w(1 2 3 a b c 5))
  end
end
