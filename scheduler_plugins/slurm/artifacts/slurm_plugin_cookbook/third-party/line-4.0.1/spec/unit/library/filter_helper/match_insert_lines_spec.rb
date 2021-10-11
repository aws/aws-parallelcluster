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

describe 'match_insert_lines? method safe mode false' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
  end

  it 'Should always be false' do
    expect(@filt.match_insert_lines?(/.*/, %w(), false)).to eq(false)
  end

  it 'Should always be false' do
    expect(@filt.match_insert_lines?(/a/, %w(a b c), false)).to eq(false)
  end
end

describe 'match_insert_lines? method safe mode true' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
  end

  it 'empty array should not match' do
    expect(@filt.match_insert_lines?(/.*/, [], true)).to eq(false)
  end

  it 'matching array should matche' do
    expect(@filt.match_insert_lines?(/a/, %w(a b c), true)).to eq(true)
  end

  it 'matching an array in the middle should match' do
    expect(@filt.match_insert_lines?(/a/, %w(b a c), true)).to eq(true)
  end

  it 'matching an array at the end should match' do
    expect(@filt.match_insert_lines?(/a/, %w(c b a), true)).to eq(true)
  end

  it 'matching an array multiple times should match' do
    expect(@filt.match_insert_lines?(/a/, %w(c b a), true)).to eq(true)
  end

  it 'not matching an array should not match' do
    expect(@filt.match_insert_lines?(/d/, %w(c b a), true)).to eq(false)
  end
end
