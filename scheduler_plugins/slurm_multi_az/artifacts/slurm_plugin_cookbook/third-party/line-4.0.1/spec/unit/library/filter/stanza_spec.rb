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

describe 'stanza method' do
  before(:each) do
    @filt = Line::Filter.new
    @current = [
      '[head1]',
      '# comment',
      '  key1 = val1',
      '# comment',
      '  key2 = val1',
      '[head2]',
      '  key2 = val2',
      '  key3 = val3',
      '[head3]',
      '  key3.1 = val1',
      '[head4]',
    ]
    @sample2 = [
      '[name.-_%@]',
      '  name.-_%@ = val1',
    ]
    @sample_repeated_stanza = [
      '[head1]',
      '  key1 = val1',
      '[head1]',
      '  key2 = val2',
    ]
    @sample_repeated_key = [
      '[head1]',
      '  key1 = val1',
      '  key1 = val2',
    ]
    @sample_value = [
      '[head1]',
      '  key1 val1',
      '  key1 val2',
    ]
    @sample_mixed = [
      '[head1]',
      '  key1 val1',
      '  key2 val2',
      '[head2]',
      '  key2 val2',
      '  key3 val1',
      '  key4 val4',
    ]
  end

  it 'should add stanza to an empty array' do
    expect(@filt.stanza([], ['newstanza', { key1: 'value1', key2: 'value2' }])).to eq(
      [
        '[newstanza]',
        '  key1 = value1',
        '  key2 = value2',
      ]
    )
  end

  it 'should add stanza to an existing array' do
    out_lines = @current.map { |line| line }
    ip = out_lines.size
    out_lines[ip] = '[newstanza]'
    out_lines[ip + 1] = '  key1 = value1'
    out_lines[ip + 2] = '  key2 = value2'
    expect(@filt.stanza(@current, ['newstanza', { key1: 'value1', key2: 'value2' }])).to eq(out_lines)
  end

  it 'should replace values in a stanza' do
    out_lines = @current.map { |line| line }
    out_lines[2] = '  key1 = replace1'
    expect(@filt.stanza(@current, ['head1', { key1: 'replace1' }])).to eq(out_lines)
  end

  it 'should replace multiple values in a stanza' do
    out_lines = @current.map { |line| line }
    out_lines[6] = '  key2 = replace2'
    out_lines[7] = '  key3 = replace3'
    expect(@filt.stanza(@current, ['head2', { key2: 'replace2', key3: 'replace3' }])).to eq(out_lines)
  end

  it 'should replace and add values in a stanza' do
    out_lines = @current.map { |line| line }
    out_lines[9] = '  newkey = insertvalue'
    out_lines[10] = '  key3.1 = replace1'
    out_lines[11] = '[head4]'
    expect(@filt.stanza(@current, ['head3', { 'key3.1' => 'replace1', newkey: 'insertvalue' }])).to eq(out_lines)
  end

  it 'should find names with all the characters in the key pattern' do
    out_lines = @sample2.map { |line| line }
    out_lines[1] = '  name.-_%@ = replace1'
    expect(@filt.stanza(@sample2, ['name.-_%@', { 'name.-_%@' => 'replace1' }])).to eq(out_lines)
  end

  it 'should use the last stanza with multiple stanzas of the same name' do
    out_lines = ['[head1]', '  key1 = val1', '[head1]', '  key1 = replace1', '  newkey = insertvalue', '  key2 = val2']
    expect(@filt.stanza(@sample_repeated_stanza, ['head1', { 'key1' => 'replace1', newkey: 'insertvalue' }])).to eq(out_lines)
  end

  it 'should use the last key with multiple keys of the same name' do
    out_lines = ['[head1]', '  newkey = insertvalue', '  key1 = val1', '  key1 = replace1']
    expect(@filt.stanza(@sample_repeated_key, ['head1', { 'key1' => 'replace1', newkey: 'insertvalue' }])).to eq(out_lines)
  end

  it 'should use the value style for keywords' do
    out_lines = ['[head1]', '  newkey insertvalue', '  key1 val1', '  key1 replace1']
    expect(@filt.stanza(@sample_value, ['head1', { 'key1' => 'replace1', newkey: 'insertvalue' }, :value])).to eq(out_lines)
  end

  it 'should update keys regardless of the order' do
    out_lines = ['[head1]', '  newkey insertvalue', '  key1 replace2', '  key2 replace1', '[head2]', '  key2 val2', '  key3 val1', '  key4 val4']
    expect(@filt.stanza(@sample_mixed, ['head1', { 'key2' => 'replace1', newkey: 'insertvalue', 'key1' => 'replace2' }, :value])).to eq(out_lines)
  end
end
