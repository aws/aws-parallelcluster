#
# Copyright:: 2019 Sous Chefs
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

describe 'next_match_after method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'An nil request should return the first match' do
    expect(@filt.next_match_after(nil, [1, 2, 3])).to eq(1)
  end

  it 'A match number should find the next highest value in matches' do
    expect(@filt.next_match_after(1, [5, 10, 15, 25])).to eq(5)
    expect(@filt.next_match_after(11, [5, 10, 15, 25])).to eq(15)
    expect(@filt.next_match_after(17, [5, 10, 15, 25])).to eq(25)
  end

  it 'A match number higher than all the matches should return the last match' do
    expect(@filt.next_match_after(27, [5, 10, 15, 25])).to eq(25)
  end

  it 'A match of an empty array should return nil' do
    expect(@filt.next_match_after(5, [])).to eq(nil)
  end
end
