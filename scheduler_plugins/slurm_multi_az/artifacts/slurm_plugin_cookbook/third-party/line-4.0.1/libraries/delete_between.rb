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

# Filter to delete lines between two matches
module Line
  class Filter
    def delete_between(current, args)
      # delete the lines matching a pattern found between lines matching two patterns
      # current is an array of lines
      # args[0] is a pattern. Delete lines after this pattern
      # args[1] is a pattern. Delete lines before this pattern
      # args[2] is a pattern. Delete the lines that match this pattern found between the after and before patterns
      # args[3] is a symbol. Include the start and end lines in the delete match. Default is :exclude. Other options are :first, :include, :last
      #
      # returns array with deleted lines
      first_pattern = verify_kind(args[0], Regexp)
      second_pattern = verify_kind(args[1], Regexp)
      delete_pattern = verify_kind(args[2], Regexp)
      ends = verify_one_of(args[3], [nil, :exclude, :first, :include, :last]) || :exclude

      first_matches = []
      second_matches = []
      current.each_index do |i|
        first_matches << i if current[i] =~ first_pattern
        second_matches << i if current[i] =~ second_pattern
      end

      start_line = first_matches.first
      end_line = second_matches.last
      if start_line && end_line && start_line <= end_line
        delete_start = [:first, :include].include?(ends) ? start_line : start_line + 1
        delete_end = [:last, :include].include?(ends) ? end_line : end_line - 1
        (delete_start..delete_end).each do |i|
          current[i] = Replacement.new(current[i], '', :delete) if current[i] =~ delete_pattern
        end
      end
      expand(current)
    end
  end
end
