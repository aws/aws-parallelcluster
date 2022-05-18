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

# Filter to replace matched lines
module Line
  class Filter
    def replace(current, args)
      # Replace each instance of a pattern line with a  set of lines
      # current is an array of lines
      # args[0] is a pattern to match a line
      # args[1] is a string or an array of lines to replace the matched lines
      # args[2] options allowed - safe
      #
      # returns array with inserted lines
      #
      match_pattern = verify_kind(args[0], Regexp)
      insert_array = prepare_insert_lines(args[1])
      options(args[2], safe: [true, false])

      verify_insert_lines(match_pattern, insert_array, @options[:safe])

      matches = []
      current.each_index { |i| matches << i if current[i] =~ match_pattern }

      matches.each do |match|
        current[match] = Replacement.new(current[match], insert_array, :replace)
      end

      expand(current)
    end
  end
end
