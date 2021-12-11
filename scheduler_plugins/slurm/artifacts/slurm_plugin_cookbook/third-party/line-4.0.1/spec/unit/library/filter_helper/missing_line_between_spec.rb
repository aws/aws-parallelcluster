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

describe 'missing_lines_between method' do
  before(:each) do
    @filt = Line::Filter.new
    @filt.safe_default = true
  end

  # missing_lines_between(current, start, match, ia)
  it 'all insert lines should be missing from an empty array' do
    expect(@filt.missing_lines_between([], 0, 0, %w(a b c))).to eq(%w(a b c))
  end

  it 'it should search after the start index' do
    expect(@filt.missing_lines_between(%w(a b c), 0, 3, %w(a b c))).to eq(%w(a))
  end

  it 'it should not include the end line in the search' do
    expect(@filt.missing_lines_between(%w(a b c), 0, 2, %w(a b c))).to eq(%w(a c))
  end

  it 'it should find all the lines that are there' do
    expect(@filt.missing_lines_between(%w(z a b c), 0, 4, %w(a b c))).to eq(%w())
  end

  it 'it should find all the lines without regard to order' do
    expect(@filt.missing_lines_between(%w(z a b c), 0, 4, %w(c a b))).to eq(%w())
  end

  it 'it should find all the lines not in the range' do
    expect(@filt.missing_lines_between(%w(a b c d e f g), 3, 6, %w(a b c d e f g))).to eq(%w(a b c d g))
  end

  it 'it should allow a large range' do
    expect(@filt.missing_lines_between(%w(a b c d e f g), 0, 20, %w(b c d e f g))).to eq(%w())
  end

  it 'it should allow for a tight range' do
    expect(@filt.missing_lines_between(%w(a b c d e f g), 3, 4, %w(a b c))).to eq(%w(a b c))
  end
end
