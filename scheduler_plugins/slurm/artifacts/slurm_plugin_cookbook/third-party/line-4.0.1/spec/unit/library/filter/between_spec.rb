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

describe 'between method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.eol = "\n"
    @ia = %w(line1 line2 line3)
    @current = %w(line3 line2 line1 c1 c2 c1 line1 c1 c2)
    @after = %w(line3 line2 line1 c1 line2 line3 c2 c1 line1 c1 c2)
    @pattern_c1 = /c1/
    @pattern_c2 = /c2/
  end

  it 'should not insert if no lines match' do
    expect(@filt.between([], [@pattern_c1, @pattern_c2, @ia])).to eq([])
  end

  it 'should insert missing lines between first and last match of c1 and c2' do
    expect(@filt.between(@current, [@pattern_c1, @pattern_c2, @ia])).to eq(@after)
  end

  it 'should insert a single line between first and last match of c1 and c2' do
    expect(@filt.between(@current, [@pattern_c1, @pattern_c2, 'string1'])).to eq(%w(line3 line2 line1 c1 string1 c2 c1 line1 c1 c2))
  end
end
