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
require 'ostruct'

describe 'helper methods' do
  before(:each) do
    @method_test = Class.new
    @method_test.extend(Line::Helper)
    @method_test.extend(DSLHelpers)
    new_resource = OpenStruct.new
    new_resource.eol = "\n"
    allow(@method_test).to receive(:new_resource).and_return(new_resource)
  end

  describe 'chomp_eol method' do
    it 'should remove trailing eol' do
      expect(@method_test.chomp_eol("line\n")).to eq('line')
    end

    it 'should raise error with embedded eol' do
      expect { @method_test.chomp_eol("embedded\ninline") }.to raise_error(ArgumentError)
    end
  end

  describe 'default_eol' do
    it 'should return an eol character' do
      expect(@method_test.default_eol).to eq("\n")
    end
  end

  describe 'filters' do
    it 'should return a new filter object' do
      expect(@method_test.filter_rep.class).to eq(Line::Filter)
    end
  end

  describe 'sensitive_default?' do
    it 'should return a default value if not set' do
      new_resource = OpenStruct.new
      allow(@method_test).to receive(:property_is_set?).with(:sensitive).and_return(false)
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
      expect(@method_test.sensitive_default).to eq(true)
      expect(new_resource.sensitive).to eq(true)
    end

    it 'should leave the value alone if property_is_set?' do
      new_resource = OpenStruct.new
      new_resource.sensitive = false
      allow(@method_test).to receive(:property_is_set?).with(:sensitive).and_return(true)
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
      expect(@method_test.sensitive_default).to eq(nil)
      expect(new_resource.sensitive).to eq(false)
    end
  end

  describe 'target_current_lines?' do
    it 'should get an array of lines' do
      File.write('/tmp/file', "foo\nbar\nlast\n")
      new_resource = OpenStruct.new
      new_resource.eol = "\n"
      new_resource.path = '/tmp/file'
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
      expect(@method_test.target_current_lines).to eq(%w(foo bar last))
    end
  end

  describe 'target_file_exist?' do
    it 'should verify file does not exist' do
      new_resource = OpenStruct.new
      new_resource.eol = "\n"
      new_resource.path = '/tmp/nofile'
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
      expect(@method_test.target_file_exist?).to eq(false)
    end

    it 'should verify file does exist' do
      File.write('/tmp/file', 'foo')
      new_resource = OpenStruct.new
      new_resource.eol = "\n"
      new_resource.path = '/tmp/file'
      allow(@method_test).to receive(:new_resource).and_return(new_resource)
      expect(@method_test.target_file_exist?).to eq(true)
    end
  end
end

# Replace the chef DSL methods
module DSLHelpers
  def property_is_set?(_property)
    false
  end

  def platform_family?(_ostype)
    false
  end
end
