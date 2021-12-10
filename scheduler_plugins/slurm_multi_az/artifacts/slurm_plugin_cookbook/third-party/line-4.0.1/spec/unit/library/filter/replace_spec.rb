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

describe 'replace method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @filt.eol = "\n"
    @ia = %w(line1 line2 line3)
    @current = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2)
    @solo_start = %w(c1 linef lineg lineh )
    @solo_middle = %w(linef c1 lineg )
    @solo_end = %w(linef lineg lineh c1)
    @allthere = %w(line3 line2 line1 line1 line2 line3 line3 line2 line1 line2 line3 line1 line1 line2 line3 c2)
    @allthere_c2 = %w(line3 line2 line1 line1 line2 line3 line3 line2 line1 line2 line3 line1 line1 line2 line3 line1 line2 line3)
    @pattern_c1 = /c1/
    @pattern_c1_c2 = /c1|c2/
  end

  it 'should not replace if no lines match' do
    expect(@filt.replace([], [@pattern_c1, @ia])).to eq([])
  end

  it 'should replace each match of c1' do
    expect(@filt.replace(@current, [@pattern_c1, @ia])).to eq(@allthere)
  end

  it 'should replace each match of c1 and c2' do
    expect(@filt.replace(@current, [@pattern_c1_c2, @ia])).to eq(@allthere_c2)
  end

  it 'should replace the first line' do
    expect(@filt.replace(@solo_start, [@pattern_c1, @ia])).to eq(%w(line1 line2 line3 linef lineg lineh))
  end

  it 'should replace the middle line' do
    expect(@filt.replace(@solo_middle, [@pattern_c1, @ia])).to eq(%w(linef line1 line2 line3 lineg))
  end

  it 'should replace the end line' do
    expect(@filt.replace(@solo_end, [@pattern_c1, @ia])).to eq(%w(linef lineg lineh line1 line2 line3))
  end

  it 'should raise error if the pattern matches the replacement lines' do
    expect { @filt.replace(@current, [@pattern_c1, ['c1 match', 'c2']]) }.to raise_error(ArgumentError)
  end

  it 'should not raise error if the pattern matches the replacement lines, force the change' do
    out_lines = @current.map { |line| line }
    out_lines[3] = 'c1 match'
    out_lines[6] = 'c1 match'
    out_lines[8] = 'c1 match'
    expect(@filt.replace(@current, [@pattern_c1, ['c1 match'], safe: false])).to eq(out_lines)
  end

  it 'should replace with a string' do
    expect(@filt.replace(@solo_middle, [@pattern_c1, 'string1'])).to eq(%w(linef string1 lineg))
  end

  it 'should replace with a multiple lines specified as a string' do
    expect(@filt.replace(@solo_middle, [@pattern_c1, "string1\nstring2"])).to eq(%w(linef string1 string2 lineg))
  end
end
