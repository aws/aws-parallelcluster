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

describe 'comment method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @filt.eol = "\n"
    @current = ['line3', 'line2', 'line1', 'c1', 'line3', 'line2', '# c1', 'line1', 'c1', 'c2']
    @solo_start = %w(c1 linef lineg lineh )
    @solo_middle = %w(linef c1 lineg )
    @solo_end = %w(linef lineg lineh c1)
    @pattern_c1 = /c1/
    @pattern_c1_c2 = /c1|c2/
    @pattern_all = /./
  end

  it 'should not change if no lines match' do
    expect(@filt.comment([], [@pattern_c1])).to eq([])
  end

  it 'should comment each match of c1' do
    out_lines = @current.map { |line| line }
    out_lines[3] = '# c1'
    out_lines[8] = '# c1'
    expect(@filt.comment(@current, [@pattern_c1])).to eq(out_lines)
  end

  it 'should comment each match of c1 and c2' do
    out_lines = @current.map { |line| line }
    out_lines[3] = '# c1'
    out_lines[8] = '# c1'
    out_lines[9] = '# c2'
    expect(@filt.comment(@current, [@pattern_c1_c2])).to eq(out_lines)
  end

  it 'should comment the first line' do
    out_lines = @solo_start.map { |line| line }
    out_lines[0] = '# c1'
    expect(@filt.comment(@solo_start, [@pattern_c1])).to eq(out_lines)
  end

  it 'should comment the middle line' do
    out_lines = @solo_middle.map { |line| line }
    out_lines[1] = '# c1'
    expect(@filt.comment(@solo_middle, [@pattern_c1])).to eq(out_lines)
  end

  it 'should comment the end line' do
    out_lines = @solo_end.map { |line| line }
    out_lines[3] = '# c1'
    expect(@filt.comment(@solo_end, [@pattern_c1])).to eq(out_lines)
  end
end
