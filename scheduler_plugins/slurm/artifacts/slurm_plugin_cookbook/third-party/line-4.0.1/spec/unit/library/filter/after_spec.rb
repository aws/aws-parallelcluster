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

describe 'after method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @filt.eol = "\n"
    @ia = %w(line1 line2 line3)
    @current = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2)
    @solo_start = %w(c1 linef lineg lineh)
    @solo_middle = %w(linef c1 lineg)
    @solo_end = %w(linef lineg lineh c1)
    @allthere = %w(line3 line2 line1 c1 line1 line3 line2 c1 line2 line3 line1 c1 line1 line2 line3 c2)
    @allthere_c2 = %w(line3 line2 line1 c1 line1 line3 line2 c1 line2 line3 line1 c1 line1 line2 line3 c2 line1 line2 line3)
    @first_match_c1 = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2)
    @last_match_c1_c2 = %w(line3 line2 line1 c1 line3 line2 c1 line1 c1 c2 line1 line2 line3)
    @pattern_c1 = /c1/
    @pattern_c1_c2 = /c1|c2/
  end

  it 'should not insert if no lines match' do
    expect(@filt.after([], [@pattern_c1, @ia, :each])).to eq([])
  end

  it 'should not insert if no lines match - first' do
    expect(@filt.after([], [@pattern_c1, @ia, :first])).to eq([])
  end

  it 'should not insert if no lines match - last' do
    expect(@filt.after([], [@pattern_c1, @ia, :last])).to eq([])
  end

  it 'should insert missing lines after each match of c1' do
    expect(@filt.after(@current, [@pattern_c1, @ia, :each])).to eq(@allthere)
  end

  it 'should insert missing lines after each match of c1 and c2' do
    expect(@filt.after(@current, [@pattern_c1_c2, @ia, :each])).to eq(@allthere_c2)
  end

  it 'should insert missing lines after the first match of c1 and c2' do
    expect(@filt.after(@current, [@pattern_c1_c2, @ia, :first])).to eq(@first_match_c1)
  end

  it 'should insert missing lines after the last match of c1 and c2' do
    expect(@filt.after(@current, [@pattern_c1_c2, @ia, :last])).to eq(@last_match_c1_c2)
  end

  it 'should insert after match of the first line - each' do
    expect(@filt.after(@solo_start, [@pattern_c1, @ia, :each])).to eq(%w(c1 line1 line2 line3 linef lineg lineh))
  end

  it 'should insert after match of the first line - first' do
    expect(@filt.after(@solo_start, [@pattern_c1, @ia, :first])).to eq(%w(c1 line1 line2 line3 linef lineg lineh))
  end

  it 'should insert after match of the first line - last' do
    expect(@filt.after(@solo_start, [@pattern_c1, @ia, :last])).to eq(%w(c1 line1 line2 line3 linef lineg lineh))
  end

  it 'should insert after match of the last line - each' do
    expect(@filt.after(@solo_end, [@pattern_c1, @ia, :each])).to eq(%w(linef lineg lineh c1 line1 line2 line3))
  end

  it 'should insert after match of the last line - first' do
    expect(@filt.after(@solo_end, [@pattern_c1, @ia, :first])).to eq(%w(linef lineg lineh c1 line1 line2 line3))
  end

  it 'should insert after match of the last line - last' do
    expect(@filt.after(@solo_end, [@pattern_c1, @ia, :last])).to eq(%w(linef lineg lineh c1 line1 line2 line3))
  end

  it 'should insert after match of a middle line - each' do
    expect(@filt.after(@solo_middle, [@pattern_c1, @ia, :each])).to eq(%w(linef c1 line1 line2 line3 lineg))
  end

  it 'should insert after match of a middle line - first' do
    expect(@filt.after(@solo_middle, [@pattern_c1, @ia, :first])).to eq(%w(linef c1 line1 line2 line3 lineg))
  end

  it 'should insert a string' do
    expect(@filt.after(@solo_middle, [@pattern_c1, 'string1', :last])).to eq(%w(linef c1 string1 lineg))
  end

  it 'should split text input into multiple lines' do
    expect(@filt.after(@solo_middle, [@pattern_c1, "string1\nstring2\n", :last])).to eq(%w(linef c1 string1 string2 lineg))
  end

  it 'should not insert a line that matches the pattern by default, nil implies safe' do
    expect { @filt.after(%w(line1 line2), [/line1/, 'line1 longer', :last]) }.to raise_error(ArgumentError)
  end

  it 'should not insert a line that matches the pattern with an explicit safe run' do
    expect { @filt.after(%w(line1 line2), [/line1/, 'line1 longer', :last, { safe: true }]) }.to raise_error(ArgumentError)
  end

  it 'should insert a line that matches the pattern during an unsafe run' do
    expect(@filt.after(%w(line1 line2), [/line1/, 'line1 longer', :last, { safe: false }])).to eq(['line1', 'line1 longer', 'line2'])
  end
end
