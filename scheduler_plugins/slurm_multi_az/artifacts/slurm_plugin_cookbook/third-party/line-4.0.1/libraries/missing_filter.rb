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

# Filter to add missing lines before or after existing lines.
module Line
  class Filter
    def missing(current, args)
      # Add a set of lines if not already present
      # current is an array of lines
      # args[0] is a string or an array of lines to add before or after the existing lines
      # args[1] :after or :before
      #
      # returns array with inserted lines
      insert_array = prepare_insert_lines(args[0])
      add_point = verify_one_of(args[1], [nil, :after, 'after', :before, 'before']) || :after

      case add_point
      when :after
        insert_lines = missing_lines_between(current, -1, current.size + 1, insert_array)
        rep = current[current.size] ? :after : :replace
        current[current.size] = Replacement.new(current[current.size], insert_lines, rep)
      when :before
        insert_lines = missing_lines_between(current, -1, current.size + 1, insert_array)
        rep = current[0] ? :before : :replace
        current[0] = Replacement.new(current[0], insert_lines, rep)
      end
      expand(current)
    end
  end
end
