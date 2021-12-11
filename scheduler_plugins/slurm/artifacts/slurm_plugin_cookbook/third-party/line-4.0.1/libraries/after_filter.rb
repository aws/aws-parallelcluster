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

# Filter to insert lines after a match
module Line
  class Filter
    def after(current, args)
      # Insert a set of lines immediately after each match of the pattern
      # current is an array of lines
      # args[0] is a pattern to match a line
      # args[1] is a string or an array of lines to insert after the matched lines
      # args[2] match instance option, each, first, last
      # args[3] options allowed - safe
      #
      # returns array with inserted lines
      match_pattern = verify_kind(args[0], Regexp)
      insert_array = prepare_insert_lines(args[1])
      select_match = verify_one_of(args[2], [nil, :each, 'each', :first, 'first', :last, 'last']) || :each
      options(args[3], safe: [true, false])

      verify_insert_lines(match_pattern, insert_array, @options[:safe])

      # find matching lines  (match object, line #, insert match, insert direction)
      matches = []
      current.each_index { |i| matches << i if current[i] =~ match_pattern }

      case select_match
      when :each
        matches.each_index do |i|
          next_match = matches[i + 1] || current.size
          insert_lines = missing_lines_between(current, matches[i], next_match, insert_array)
          current[matches[i]] = Replacement.new(current[matches[i]], insert_lines, :after)
        end
      when :first
        if matches.any?
          next_match = matches[2] || current.size
          match = matches.first
          insert_lines = missing_lines_between(current, match, next_match, insert_array)
          current[match] = Replacement.new(current[match], insert_lines, :after)
        end
      when :last
        if matches.any?
          next_match = current.size
          match = matches.last
          insert_lines = missing_lines_between(current, match, next_match, insert_array)
          current[match] = Replacement.new(current[match], insert_lines, :after)
        end
      end
      expand(current)
    end
  end
end
