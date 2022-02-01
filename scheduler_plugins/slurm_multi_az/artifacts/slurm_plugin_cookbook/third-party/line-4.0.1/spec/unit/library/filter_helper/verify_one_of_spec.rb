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

describe 'verify_one_of method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'should match and return the original' do
    expect(@filt.verify_one_of('a', 'a')).to eq('a')
  end

  it 'should match and return the original string' do
    expect(@filt.verify_one_of('a', ['a', :a])).to eq('a')
  end

  it 'should match and return the original symbol' do
    expect(@filt.verify_one_of(:a, ['a', :a])).to eq(:a)
  end

  it 'should differentiate between strings and symbols' do
    expect { @filt.verify_one_of(:a, ['a']) }.to raise_error(ArgumentError)
  end
end
