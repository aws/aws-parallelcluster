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

describe 'delete_between method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @ia = %w(line1 line2 line3)
    @current = %w(line3 line2 line1 c1 c2 c1 line1 c1 c2)
    @out = @current.clone
    @pattern_c1 = /c1/
    @pattern_c2 = /c2/
    @pattern_all = /^/
  end

  it 'should not delete if no lines' do
    expect(@filt.delete_between([], [@pattern_c1, @pattern_c2, @pattern_all])).to eq([])
  end

  it 'should not delete if no matches' do
    expect(@filt.delete_between(@current.clone, [@pattern_c1, @pattern_c2, /d1/])).to eq(@current)
  end

  it 'should not delete if no matches between' do
    expect(@filt.delete_between(@current.clone, [/line3/, /line2/, /d1/])).to eq(@current)
  end

  it 'should delete all lines' do
    expect(@filt.delete_between(@current.clone, [/^/, /^/, /^/, :include])).to eq([])
  end

  it 'should delete including the end match line' do
    expect(@filt.delete_between(@current.clone, [/line3/, /line1/, /^/, :last])).to eq(%w(line3 c1 c2))
  end

  it 'should delete including the start match line' do
    expect(@filt.delete_between(@current.clone, [/line3/, /line1/, /^/, :first])).to eq(%w(line1 c1 c2))
  end

  it 'should delete including both start and end match lines' do
    expect(@filt.delete_between(@current.clone, [/line3/, /line1/, /^/, :include])).to eq(%w(c1 c2))
  end

  it 'should delete all lines in the file' do
    expect(@filt.delete_between(@current.clone, [/^/, /^/, /^/, :include])).to eq([])
  end

  it 'should delete between first and last lines' do
    expect(@filt.delete_between(@current.clone, [/line3/, @pattern_c2, /^/])).to eq(%w(line3 c2))
  end

  it 'should not delete if matches are out of order' do
    expect(@filt.delete_between(@current.clone, [/line2/, /line3/, /^/])).to eq(@current)
  end

  it 'should delete between matches' do
    expect(@filt.delete_between(@current.clone, [@pattern_c1, @pattern_c1, /^/])).to eq(%w(line3 line2 line1 c1 c1 c2))
  end

  it 'should delete between matches' do
    expect(@filt.delete_between(@current.clone, [@pattern_c1, @pattern_c2, /line/])).to eq(%w(line3 line2 line1 c1 c2 c1 c1 c2))
  end

  it 'should delete between selected matches' do
    expect(@filt.delete_between(@current.clone, [@pattern_c1, @pattern_c1, /line1/])).to eq(%w(line3 line2 line1 c1 c2 c1 c1 c2))
  end

  it 'should delete a single between' do
    expect(@filt.delete_between(%w(l1 l2 l3), [/l1/, /l3/, /^/])).to eq(%w(l1 l3))
  end
end
