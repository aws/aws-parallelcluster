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

# Common filter methods and useful classes
module Line
  class Filter
    def missing_lines_between(current, start, next_match, insert_lines)
      # insert_lines is an array of lines to insert
      # find the lines that are alreay between the start and next_match search limits of the lines array
      # filter those lines out of the line array
      raise ArgumentError unless start <= next_match
      missing_lines = insert_lines.dup
      lines_between(current, start, next_match).each do |line|
        match_line = missing_lines.index(line)
        missing_lines[match_line] = nil if match_line
      end
      missing_lines.compact
    end

    def prepare_insert_lines(inserts)
      chomp_array([verify_kind(string_to_lines(inserts), [Array, String])].flatten)
    end

    def string_to_lines(line)
      line.respond_to?(:split) ? line.split(eol) : line
    end

    def chomp_array(lines)
      lines.map do |line|
        chomp_eol(line)
      end
    end

    def chomp_eol(line)
      fixed = line.chomp(eol)
      raise ArgumentError, "Line #{fixed} has embedded EOL characters, not allowed for this resource" if fixed =~ /#{eol}/
      fixed
    end

    attr_accessor :eol

    def expand(lines)
      new_lines = []
      lines.each do |line|
        # NOTE: - want to do *lines to add them instead adding an array
        new_lines.push line.class == Replacement ? line.insert : line
      end
      new_lines.compact.flatten # add the lines better so we don't need this
    end

    def lines_between(current, start, next_match)
      slice_count = start < next_match ? next_match - (start + 1) : 0
      lines = current.slice(start + 1, slice_count)
      lines || []
    end

    def match_insert_lines?(match_pattern, insert_lines, safe)
      return false unless safe
      insert_lines.any? do |line|
        line =~ match_pattern
      end
    end

    def match_limits(request, lookfor)
      return false if [request].flatten.compact.empty?
      ([request].flatten.compact & lookfor.flatten.compact).any?
    end

    def next_match_after(start, matches)
      matches.select { |m| start.to_i <= m }.min || matches.last
    end

    def options(values, allowed)
      # allowed is {option_name: [settings]}
      @options ||= {}
      @options[:safe] ||= safe_default
      return @options unless values
      values.each do |key, setting|
        raise ArgumentError, "Option key  #{key} should be one of #{allowed.keys}" unless allowed.key?(key.to_sym)
        raise ArgumentError, "Option setting of #{key} should be one of #{allowed[key.to_sym]}" unless allowed[key.to_sym].include?(setting)
        @options[key.to_sym] = setting
      end
      @options
    end

    def safe_default
      # @safe must be defined by a call to safe_default= by the filter resource
      @safe
    end

    def safe_default=(option)
      @safe = option
    end

    def verify_insert_lines(match_pattern, insert_lines, safe)
      return unless safe
      error_message = 'Inserted lines should not match the insert location pattern'
      insert_lines.each do |line|
        raise ArgumentError, "Error - #{error_message} line #{line} matches #{match_pattern}" if line =~ match_pattern
      end
    end

    def verify_kind(value, kinds)
      raise ArgumentError, "Wrong class #{value} with class #{value.class} should be one of #{kinds}" unless [kinds].flatten.include?(value.class)
      value
    end

    def verify_one_of(value, allowed)
      raise ArgumentError, "Value #{value} should be one of #{allowed}" unless [allowed].flatten.include?(value)
      value
    end

    def verify_all_of(value, allowed)
      a = [allowed].flatten
      v = [value].flatten
      raise ArgumentError, "Values #{v} should all be in #{a}" unless (v & a) == v
      [value].flatten.compact
    end
  end

  class Replacement
    def initialize(original, additional, direction)
      @original = original.nil? ? nil : original.dup
      @additional = additional
      @direction = direction # replace, before, after, remove
    end

    def insert
      case @direction
      when :after
        [@additional].unshift(@original)
      when :before
        [@additional].push(@original)
      when :delete
        nil
      when :replace
        [@additional]
      else
        [@original]
      end
    end

    def add(lines, direction)
      case direction
      when :after
        @additional.push(lines)
      when :before
        @additional.push(@original)
      when :replace
        @additional = lines
      end
    end
  end
end
