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
require 'ostruct'

describe 'list_helper methods' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::ListHelper)
    new_resource = OpenStruct.new
    new_resource.delim = [ '.', '(', ')']
    new_resource.eol = "\n"
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'regexdelim method' do
    it 'should return escaped delimeters' do
      expect(@method_test.regexdelim).to eq(['\\.', '\\(', '\\)'])
    end
  end

  describe 'escape_delims method' do
    it 'should return escaped delimeters' do
      expect(@method_test.escape_delims).to eq(['\\.', '\\(', '\\)'])
    end
  end

  describe 'line_parts method' do
    it 'should seaparate an unterminated list' do
      expect(@method_test.line_parts('list = one two', 'list\s*= ', '')).to eq(['list = ', 'one two', ''])
    end

    it 'should return an empty list' do
      expect(@method_test.line_parts('list = ', 'list\s*= ', '')).to eq(['list = ', '', ''])
    end

    it 'should separate a terminated list' do
      expect(@method_test.line_parts('list = "one two"', 'list\s*=\s*"', '"')).to eq(['list = "', 'one two', '"'])
    end

    it 'should separate a minimal pattern quoted list' do
      expect(@method_test.line_parts('"one two"', '^"', '"')).to eq(['"', 'one two', '"'])
    end

    it 'should separate a minimal pattern list' do
      expect(@method_test.line_parts('one two', '^', '')).to eq(['', 'one two', ''])
    end

    it 'should separate a nil pattern list' do
      expect(@method_test.line_parts('one two', nil, '')).to eq(['', 'one two', ''])
    end
  end
end

describe 'list_helper methods single delimeter' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::ListHelper)
    new_resource = OpenStruct.new
    new_resource.delim = [' ']
    new_resource.entry = 'd'
    new_resource.eol = "\n"
    new_resource.pattern = /^/
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'insert_list_entry' do
    it 'should do nothing if entry exists' do
      expect(@method_test.insert_list_entry(['a b c d'])).to eq(['a b c d'])
    end
  end

  describe 'insert_list_entry' do
    it 'should add the entry' do
      expect(@method_test.insert_list_entry(['a b c'])).to eq(['a b c d'])
    end
  end

  describe 'insert_into_empty_list' do
    it 'should add the entry' do
      expect(@method_test.insert_list_entry([''])).to eq(['d'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the last entry and remove white space' do
      expect(@method_test.delete_list_entry(['a b c d  '])).to eq(['a b c'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the first entry' do
      expect(@method_test.delete_list_entry(['d a b c'])).to eq(['a b c'])
    end
  end
end

describe 'list_helper methods single delimeter with ends_with' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::ListHelper)
    new_resource = OpenStruct.new
    new_resource.delim = [' ']
    new_resource.ends_with = '"'
    new_resource.entry = 'd'
    new_resource.eol = "\n"
    new_resource.pattern = /^"/
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'insert_list_entry' do
    it 'should do nothing if entry exists' do
      expect(@method_test.insert_list_entry(['"a b c"'])).to eq(['"a b c d"'])
    end
  end

  describe 'insert_list_entry' do
    it 'should do inset into an empty list' do
      expect(@method_test.insert_list_entry(['""'])).to eq(['"d"'])
    end
  end

  describe 'insert_list_entry' do
    it 'should add the entry' do
      expect(@method_test.insert_list_entry(['"a b c"'])).to eq(['"a b c d"'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the last entry and remove white space' do
      expect(@method_test.delete_list_entry(['"a b c d  "'])).to eq(['"a b c"'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the first entry' do
      expect(@method_test.delete_list_entry(['"d a b c"'])).to eq(['"a b c"'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the only entry' do
      expect(@method_test.delete_list_entry(['"d"'])).to eq(['""'])
    end
  end
  # TODO: add a test to show how list prefix white space is kept for compatibility reasons
end

describe 'list_helper methods single non whitespace delimeter with ends_with' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::ListHelper)
    new_resource = OpenStruct.new
    new_resource.delim = [',']
    new_resource.ends_with = '"'
    new_resource.entry = 'd'
    new_resource.eol = "\n"
    new_resource.pattern = /"/
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'insert_list_entry' do
    it 'should do nothing if entry exists' do
      expect(@method_test.insert_list_entry(['"a,b,c"'])).to eq(['"a,b,c,d"'])
    end
  end

  describe 'insert_list_entry' do
    it 'should do inset into an empty list' do
      expect(@method_test.insert_list_entry(['""'])).to eq(['"d"'])
    end
  end

  describe 'insert_list_entry' do
    it 'should add the entry' do
      expect(@method_test.insert_list_entry(['"a,b,c"'])).to eq(['"a,b,c,d"'])
    end
  end

  describe 'delete_list_entry' do
    it 'should delete the last entry and remove white space' do
      expect(@method_test.delete_list_entry(['"a,b,c,d  "'])).to eq(['"a,b,c"'])
    end
    it 'should delete the last entry and remove trailing delimeters' do
      expect(@method_test.delete_list_entry(['"a,b,c,d,  "'])).to eq(['"a,b,c"'])
    end
    it 'should delete the last entry' do
      expect(@method_test.delete_list_entry(['"a,b,c,d"'])).to eq(['"a,b,c"'])
    end
    it 'should delete the first entry' do
      expect(@method_test.delete_list_entry(['"d,a,b,c"'])).to eq(['"a,b,c"'])
    end
    it 'should delete the only entry' do
      expect(@method_test.delete_list_entry(['"d"'])).to eq(['""'])
    end
  end
end

describe 'list_helper methods single delimeter' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::ListHelper)
    new_resource = OpenStruct.new
    new_resource.delim = [' ']
    new_resource.entry = 'rd.lvm'
    new_resource.eol = "\n"
    new_resource.pattern = /^/
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'entries have a partial match with the target entry' do
    it 'should insert the entry' do
      expect(@method_test.insert_list_entry(['rd.lvm.lv=centos/root quiet'])).to eq(['rd.lvm.lv=centos/root quiet rd.lvm'])
    end
    it 'should delete the entry' do
      expect(@method_test.delete_list_entry(['rd.lvm.lv=centos/root rd.lvm quiet'])).to eq(['rd.lvm.lv=centos/root quiet'])
    end
  end
end

describe 'list_helper methods two delimeters' do
  describe 'add to list' do
    before(:each) do
      @method_test = Class.new
      @method_test.extend(Line::ListHelper)
      new_resource = OpenStruct.new
      new_resource.delim = [',', '"']
      new_resource.entry = '192.168.0.0/16'
      new_resource.eol = "\n"
      new_resource.pattern = /ip=/
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.insert_list_entry(['nl='])).to eq(['nl='])
    end

    it 'should add an entry to an empty list' do
      expect(@method_test.insert_list_entry(['ip='])).to eq(['ip="192.168.0.0/16"'])
    end

    it 'should add an entry to a list' do
      expect(@method_test.insert_list_entry(['ip="1.1.1.0/8"'])).to eq(['ip="1.1.1.0/8","192.168.0.0/16"'])
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.delete_list_entry(['nl='])).to eq(['nl='])
    end

    it 'should delete the last entry' do
      expect(@method_test.delete_list_entry(['ip="192.168.0.0/16"'])).to eq(['ip='])
    end

    it 'should delete an entry from a list' do
      expect(@method_test.delete_list_entry(['ip="1.1.1.0/8","192.168.0.0/16"'])).to eq(['ip="1.1.1.0/8"'])
      expect(@method_test.delete_list_entry(['ip="192.168.0.0/16","1.1.1.0/8"'])).to eq(['ip="1.1.1.0/8"'])
    end
  end

  describe 'add to list with list ends_with' do
    before(:each) do
      @method_test = Class.new
      @method_test.extend(Line::ListHelper)
      new_resource = OpenStruct.new
      new_resource.delim = [',', '"']
      new_resource.ends_with = ')'
      new_resource.entry = '192.168.0.0/16'
      new_resource.eol = "\n"
      new_resource.pattern = /ip=\(/
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.insert_list_entry(['nl=()'])).to eq(['nl=()'])
    end

    it 'should add an entry to an empty list' do
      expect(@method_test.insert_list_entry(['ip=()'])).to eq(['ip=("192.168.0.0/16")'])
    end

    it 'should add an entry to a list' do
      expect(@method_test.insert_list_entry(['ip=("1.1.1.0/8")'])).to eq(['ip=("1.1.1.0/8","192.168.0.0/16")'])
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.delete_list_entry(['nl=()'])).to eq(['nl=()'])
    end

    it 'should delete the last entry' do
      expect(@method_test.delete_list_entry(['ip=("192.168.0.0/16")'])).to eq(['ip=()'])
    end

    it 'should delete an entry from a list' do
      expect(@method_test.delete_list_entry(['ip=("1.1.1.0/8","192.168.0.0/16")'])).to eq(['ip=("1.1.1.0/8")'])
      expect(@method_test.delete_list_entry(['ip=("192.168.0.0/16","1.1.1.0/8")'])).to eq(['ip=("1.1.1.0/8")'])
    end
  end
end

describe 'list_helper methods three delimeters' do
  describe 'add to list' do
    before(:each) do
      @method_test = Class.new
      @method_test.extend(Line::ListHelper)
      new_resource = OpenStruct.new
      new_resource.delim = [',', '{', '}']
      new_resource.entry = '192.168.0.0/16'
      new_resource.eol = "\n"
      new_resource.pattern = /ip=/
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.insert_list_entry(['nl='])).to eq(['nl='])
    end

    it 'should add an entry to an empty list' do
      expect(@method_test.insert_list_entry(['ip='])).to eq(['ip={192.168.0.0/16}'])
    end

    it 'should add an entry to a list' do
      expect(@method_test.insert_list_entry(['ip={1.1.1.0/8}'])).to eq(['ip={1.1.1.0/8},{192.168.0.0/16}'])
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.delete_list_entry(['nl='])).to eq(['nl='])
    end

    it 'should delete the last entry' do
      expect(@method_test.delete_list_entry(['ip={192.168.0.0/16}'])).to eq(['ip='])
    end

    it 'should delete an entry from a list' do
      expect(@method_test.delete_list_entry(['ip={1.1.1.0/8},{192.168.0.0/16}'])).to eq(['ip={1.1.1.0/8}'])
      expect(@method_test.delete_list_entry(['ip={192.168.0.0/16},{1.1.1.0/8}'])).to eq(['ip={1.1.1.0/8}'])
    end
  end

  describe 'add to list with list ends_with' do
    before(:each) do
      @method_test = Class.new
      @method_test.extend(Line::ListHelper)
      new_resource = OpenStruct.new
      new_resource.delim = [',', '{', '}']
      new_resource.ends_with = ')'
      new_resource.entry = '192.168.0.0/16'
      new_resource.eol = "\n"
      new_resource.pattern = /ip=\(/
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.insert_list_entry(['nl=()'])).to eq(['nl=()'])
    end

    it 'should add an entry to an empty list' do
      expect(@method_test.insert_list_entry(['ip=()'])).to eq(['ip=({192.168.0.0/16})'])
    end

    it 'should add an entry to a list' do
      expect(@method_test.insert_list_entry(['ip=({1.1.1.0/8})'])).to eq(['ip=({1.1.1.0/8},{192.168.0.0/16})'])
    end

    it 'should leave things alone if the pattern doesnt match' do
      expect(@method_test.delete_list_entry(['nl=()'])).to eq(['nl=()'])
    end

    it 'should delete the last entry' do
      expect(@method_test.delete_list_entry(['ip=({192.168.0.0/16})'])).to eq(['ip=()'])
    end

    it 'should delete an entry from a list' do
      expect(@method_test.delete_list_entry(['ip=({1.1.1.0/8},{192.168.0.0/16})'])).to eq(['ip=({1.1.1.0/8})'])
      expect(@method_test.delete_list_entry(['ip=({192.168.0.0/16},{1.1.1.0/8})'])).to eq(['ip=({1.1.1.0/8})'])
    end
  end
end
