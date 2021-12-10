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

describe 'missing method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
    @filt.eol = "\n"
    @ia = %w(line1 line2 line3)
    @all = %w(line3 line2 line1 c1)
    @none = %w(c1 linef)
    @some = %w(line1 linef)
    @some_mid = %w(c1 line1 line2 linef)
    @some_end = %w(c1 line3)
    @empty = %w()
  end

  it 'should add lines to empty files after' do
    expect(@filt.missing(@empty, [@ia, :after])).to eq(%w(line1 line2 line3))
  end

  it 'should add lines to empty files before' do
    expect(@filt.missing(@empty, [@ia, :before])).to eq(%w(line1 line2 line3))
  end

  it 'should not add if lines are already there after' do
    expect(@filt.missing(@all, [@ia, :after])).to eq(%w(line3 line2 line1 c1))
  end

  it 'should not add if lines are already there before' do
    expect(@filt.missing(@all, [@ia, :before])).to eq(%w(line3 line2 line1 c1))
  end

  it 'should split input text lines' do
    expect(@filt.missing(@none, ["string1\nstring2\n", :after])).to eq(%w(c1 linef string1 string2))
  end

  it 'should add missing lines - all missing after' do
    expect(@filt.missing(@none, [@ia, :after])).to eq(%w(c1 linef line1 line2 line3))
  end

  it 'should add missing lines - all missing before' do
    expect(@filt.missing(@none, [@ia, :before])).to eq(%w(line1 line2 line3 c1 linef))
  end

  it 'should add missing lines - some missing after' do
    expect(@filt.missing(@some, [@ia, :after])).to eq(%w(line1 linef line2 line3))
  end

  it 'should add missing lines - some missing before' do
    expect(@filt.missing(@some, [@ia, :before])).to eq(%w(line2 line3 line1 linef))
  end

  it 'should add missing lines - some in middle after' do
    expect(@filt.missing(@some_mid, [@ia, :after])).to eq(%w(c1 line1 line2 linef line3))
  end

  it 'should add missing lines - some in middle before' do
    expect(@filt.missing(@some_mid, [@ia, :before])).to eq(%w(line3 c1 line1 line2 linef))
  end

  it 'should add missing lines - some at end after' do
    expect(@filt.missing(@some_end, [@ia, :after])).to eq(%w(c1 line3 line1 line2))
  end

  it 'should add missing lines - some at end before' do
    expect(@filt.missing(@some_end, [@ia, :before])).to eq(%w(line1 line2 c1 line3))
  end
end
