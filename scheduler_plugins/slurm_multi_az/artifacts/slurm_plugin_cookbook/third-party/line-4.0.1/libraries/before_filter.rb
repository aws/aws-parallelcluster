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

# Filter to insert lines before a match
module Line
  class Filter
    def before(current, args)
      # Insert a set of lines before a match of the pattern.
      # Inserts only the missing lines
      # Lines are missing if not between matches of the pattern
      # Inserts do not care about the order of the lines
      #   :first insert any lines not found (start -> match line) before the first match
      #   :last insert any lines not found (match.last -1 -> match.last line) before the last match
      #   :each insert any lines not found (start -> match & match -1 -> match line) before each match
      # current is an array of lines
      # args[0] is a pattern to match a line
      # args[1] is a string or an array of lines to insert before the matched lines
      # args[2] match instance option, each, first, last
      # args[3] options allowed - safe
      #
      # returns array with inserted lines
      match_pattern = verify_kind(args[0], Regexp)
      insert_array = prepare_insert_lines(args[1])
      select_match = verify_one_of(args[2], [nil, :each, 'each', :first, 'first', :last, 'last']) || :each
      options(args[3], safe: [true, false])

      verify_insert_lines(match_pattern, insert_array, @options[:safe])

      # find lines matching the pattern
      matches = []
      current.each_index { |i| matches << i if current[i] =~ match_pattern }

      case select_match
      when :each
        previous = -1
        matches.each do |match|
          insert_lines = missing_lines_between(current, previous, match, insert_array)
          current[match] = Replacement.new(current[match], insert_lines, :before)
          previous = match
        end
      when :first
        if matches.any?
          previous = -1
          match = matches.first
          insert_lines = missing_lines_between(current, previous, match, insert_array)
          current[match] = Replacement.new(current[match], insert_lines, :before)
        end
      when :last
        if matches.any?
          previous = matches[-2] || -1
          match = matches.last
          insert_lines = missing_lines_between(current, previous, match, insert_array)
          current[match] = Replacement.new(current[match], insert_lines, :before)
        end
      end
      expand(current)
    end
  end
end
