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

describe 'match_limits method' do
  before(:each) do
    @filt = Line::Filter.new
  end

  it 'An empty request should be ok' do
    expect(@filt.match_limits([], [])).to eq(false)
    expect(@filt.match_limits([nil], [])).to eq(false)
    expect(@filt.match_limits([nil], [nil, :next, :first])).to eq(false)
  end

  it 'A single matching request should be true' do
    expect(@filt.match_limits([:next], [nil, :next, :first])).to eq(true)
  end

  it 'A empty default should not match' do
    expect(@filt.match_limits([], [:next])).to eq(false)
  end

  it 'An array with multiple matches should be true' do
    expect(@filt.match_limits([:next], [nil, :next, :first])).to eq(true)
  end

  it 'An array with a non matching entry matches should be false' do
    expect(@filt.match_limits([:short], [nil, :next, :first])).to eq(false)
  end
end
