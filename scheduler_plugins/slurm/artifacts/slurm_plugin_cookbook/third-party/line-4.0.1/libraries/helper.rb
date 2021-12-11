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

module Line
  # Helper methods to use in resources
  module Helper
    # filter ::= <code> | { <code> => <args> }
    # args ::= <String> | <Array>
    # code ::= <Symbol> | <Method> | <Proc>
    # Symbol ::= :after | :before | :between | :comment | :missing | :replace | :stanza | :substitue

    def apply_filter(filter)
      case filter
      when Hash
        filter.each do |code, args|
          invoke_filter(code, args)
        end
      else
        invoke_filter(filter, nil)
      end
    end

    def backup_if_true
      new_resource.backup = 5 if new_resource.backup == true
    end

    def chomp_eol(line)
      fixed = line.chomp(new_resource.eol)
      raise ArgumentError, "Line #{line} has embedded EOL characters, not allowed for this resource" if fixed =~ /#{new_resource.eol}/
      fixed
    end

    def default_eol
      new_resource.eol = platform_family?('windows') ? "\r\n" : "\n" unless property_is_set?(:eol)
      new_resource.eol
    end

    def filter_method(code)
      raise ArgumentError, "Unknown filter, #{code}, specified" unless filter_rep.public_methods.include?(code)
      filter_rep.method(code)
    end

    def filter_rep
      unless @filter_rep
        @filter_rep ||= Line::Filter.new
        @filter_rep.safe_default = new_resource.safe
        @filter_rep.eol = new_resource.eol
      end
      @filter_rep
    end

    def invoke_filter(code, args)
      code = filter_method(code) if code.is_a?(Symbol)
      @new = code.call(@new, args) if code.is_a?(Method) || code.is_a?(Proc)
    end

    def raise_not_found
      raise "File #{new_resource.path} not found" unless target_file_exist? || new_resource.ignore_missing
    end

    def sensitive_default
      new_resource.sensitive = true unless property_is_set?(:sensitive)
    end

    def target_current_lines
      target_file_exist? ? ::File.binread(new_resource.path).split(new_resource.eol) : []
    end

    def target_file_exist?
      @target_file_exist ||= ::File.exist?(new_resource.path.to_s)
    end
  end
end
