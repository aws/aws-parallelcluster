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

describe 'before method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @filt.eol = "\n"
    @ia = %w(line1 line2 line3)
    @current = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2)
    @solo_start = %w(c1 linef lineg lineh )
    @solo_middle = %w(linef c1 lineg )
    @solo_end = %w(linef lineg lineh c1)
    @allthere = %w(line3 line2 line1 c1 line3 line2 line1 c1 line1 line2 line3 c1 c2)
    @allthere_c2 = %w(line3 line2 line1 c1 line3 line2 line1 c1 line1 line2 line3 c1 line1 line2 line3 c2)
    @first_match_c1 = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2)
    @last_match_c1 = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 line1 line2 line3 c2)
    @pattern_c1 = /c1/
    @pattern_c1_c2 = /c1|c2/
  end

  it 'should not insert if no lines match' do
    expect(@filt.before([], [@pattern_c1, @ia, :each])).to eq([])
  end

  it 'should not insert if no lines match - first' do
    expect(@filt.before([], [@pattern_c1, @ia, :first])).to eq([])
  end

  it 'should not insert if no lines match - last' do
    expect(@filt.before([], [@pattern_c1, @ia, :last])).to eq([])
  end

  it 'should insert missing lines before each match of c1' do
    expect(@filt.before(@current, [@pattern_c1, @ia, :each])).to eq(@allthere)
  end

  it 'should insert missing lines before each match of c1 and c2' do
    expect(@filt.before(@current, [@pattern_c1_c2, @ia, :each])).to eq(@allthere_c2)
  end

  it 'should insert missing lines before the first match of c1 and c2' do
    expect(@filt.before(@current, [@pattern_c1_c2, @ia, :first])).to eq(@first_match_c1)
  end

  it 'should insert missing lines before the last match of c1 and c2' do
    expect(@filt.before(@current, [@pattern_c1_c2, @ia, :last])).to eq(@last_match_c1)
  end

  it 'should split text into multiple lines for inserting' do
    expect(@filt.before(@solo_start, [@pattern_c1, "string1\nstring2\n", :first])).to eq(%w(string1 string2 c1 linef lineg lineh))
  end

  it 'should insert before match of the first line - each' do
    expect(@filt.before(@solo_start, [@pattern_c1, @ia, :each])).to eq(%w(line1 line2 line3 c1 linef lineg lineh))
  end

  it 'should insert before match of the first line - first' do
    expect(@filt.before(@solo_start, [@pattern_c1, @ia, :first])).to eq(%w(line1 line2 line3 c1 linef lineg lineh))
  end

  it 'should insert before match of the first line - last' do
    expect(@filt.before(@solo_start, [@pattern_c1, @ia, :last])).to eq(%w(line1 line2 line3 c1 linef lineg lineh))
  end

  it 'should insert before match of the last line - each' do
    expect(@filt.before(@solo_end, [@pattern_c1, @ia, :each])).to eq(%w(linef lineg lineh line1 line2 line3 c1))
  end

  it 'should insert before match of the last line - first' do
    expect(@filt.before(@solo_end, [@pattern_c1, @ia, :first])).to eq(%w(linef lineg lineh line1 line2 line3 c1))
  end

  it 'should insert before match of the last line - last' do
    expect(@filt.before(@solo_end, [@pattern_c1, @ia, :last])).to eq(%w(linef lineg lineh line1 line2 line3 c1))
  end

  it 'should insert before match of a middle line - each' do
    expect(@filt.before(@solo_middle, [@pattern_c1, @ia, :each])).to eq(%w(linef line1 line2 line3 c1 lineg))
  end

  it 'should insert before match of a middle line - first' do
    expect(@filt.before(@solo_middle, [@pattern_c1, @ia, :first])).to eq(%w(linef line1 line2 line3 c1 lineg))
  end

  it 'should insert before match of a middle line - last' do
    expect(@filt.before(@solo_middle, [@pattern_c1, @ia, :last])).to eq(%w(linef line1 line2 line3 c1 lineg))
  end

  it 'should insert a string' do
    expect(@filt.before(@solo_middle, [@pattern_c1, 'string1', :last])).to eq(%w(linef string1 c1 lineg))
  end
end
