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

describe 'replace_between method' do
  before(:each) do
    @filter = Line::Filter.new
    @filter.eol = "\n"
    @filter.safe_default = true
    @current = %w(line3 line2 line1 c1 c2 c1 line1 c1 c2)
    @out = @current.clone
    @pattern_c1 = /c1/
    @pattern_c2 = /c2/
    @new_lines = %w(new1 new2 new3)
  end

  it 'should not replace if no lines' do
    expect(@filter.replace_between([], [@pattern_c1, @pattern_c2, @new_lines])).to eq([])
  end

  it 'should replace all lines' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, :include])).to eq(%w(new1 new2 new3))
  end

  it 'should replace including the end match line' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, :last])).to eq(%w(line3 new1 new2 new3))
  end

  it 'should replace including the start match line' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, :first])).to eq(%w(new1 new2 new3 c2))
  end

  it 'should replace excluding both start and end match lines' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, :exclude])).to eq(%w(line3 new1 new2 new3 c2))
  end

  it 'should replace excluding both start and end match lines by default' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines])).to eq(%w(line3 new1 new2 new3 c2))
  end

  it 'should replace picking the first match of the end pattern' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, :next])).to eq(%w(line3 new1 new2 new3 c2 c1 line1 c1 c2))
  end

  it 'should replace picking the first match of the end pattern, include the starting and ending patterns' do
    expect(@filter.replace_between(@current.clone, [/line3/, /c2/, @new_lines, [:next, :include]])).to eq(%w(new1 new2 new3 c1 line1 c1 c2))
  end

  it 'should replace between first and last lines' do
    expect(@filter.replace_between(@current.clone, [/line3/, @pattern_c2, @new_lines])).to eq(%w(line3 new1 new2 new3 c2))
  end

  it 'should not replace if matches are out of order' do
    expect(@filter.replace_between(@current.clone, [/line1/, /line3/, @new_lines])).to eq(@current)
  end

  it 'should replace between matches' do
    expect(@filter.replace_between(@current.clone, [@pattern_c1, @pattern_c1, @new_lines])).to eq(%w(line3 line2 line1 c1 new1 new2 new3 c1 c2))
  end

  it 'should replace between matches' do
    expect(@filter.replace_between(@current.clone, [@pattern_c1, @pattern_c2, @new_lines])).to eq(%w(line3 line2 line1 c1 new1 new2 new3 c2))
  end

  it 'should raise an error if an unsafe condition occurs, pattern will add more lines with each run' do
    expect { @filter.replace_between(@current.clone, [@pattern_c1, @pattern_c2, %w(c0 c1 c2), nil]) }.to raise_error(ArgumentError)
  end

  it 'should not raise an error if outer bounds match' do
    expect { @filter.replace_between(@current.clone, [@pattern_c1, @pattern_c2, %w(c1 c0 c3 c2), :include]) }.not_to raise_error
  end

  it 'should not raise an error if an unsafe condition occurs and safe is false' do
    expect { @filter.replace_between(@current.clone, [@pattern_c1, @pattern_c2, %w(c0 c1 c2), nil, { safe: false }]) }.not_to raise_error
    expect(@filter.replace_between(@current.clone, [@pattern_c1, @pattern_c2, %w(c0 c1 c2), nil, { safe: false }])).to eq(%w(line3 line2 line1 c1 c0 c1 c2 c2))
  end

  it 'should process include correctly for a small file' do
    expect(@filter.replace_between(%w(line1 line2 line3), [/line1/, /line3/, %w(rep1 rep2), :include])).to eq(%w(rep1 rep2))
  end
end
