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

describe 'verify_kind method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'should match single class and return the verified value' do
    expect(@filt.verify_kind([1, 2, 3], Array)).to eq([1, 2, 3])
  end

  it 'should match class in an array of classes ' do
    expect(@filt.verify_kind([], [Array])).to eq([])
  end

  it 'should match class in an array of many classes ' do
    expect(@filt.verify_kind([], [Regexp, Array, Hash])).to eq([])
  end

  it 'should raise an exception if missing from the array' do
    expect { @filt.verify_kind([], [Regexp, Hash]) }.to raise_error(ArgumentError)
  end

  it 'should match class in an array of many classes ' do
    expect(@filt.verify_kind(/.*/, [Regexp, Array, Hash])).to eq(/.*/)
  end
end
