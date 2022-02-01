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

# Filter to substitute in lines that  match
module Line
  class Filter
    def substitute(current, args)
      # current is an array of lines
      # args[0] is a pattern to match a line or a string in a line
      # args[1] is a pattern to match and substitute for, defaults to arg[0]
      # args[2] is the string or hash to replace the sub pattern with # no embedded EOL characters
      # args[3] options allowed - safe
      #
      # returns array with inserted lines
      #
      # error condition - If the substitute string will match a line after replacement
      #  it is possible for the file size to increase after every converge. Use force
      # to ignore the possible error.
      match_pattern = verify_kind(args[0], Regexp)
      sub_pattern = verify_kind(args[1], [Regexp]) || match_pattern
      substitute_str = verify_kind(args[2], [NilClass, String, Hash]) # String or Hash
      options(args[3], safe: [true, false])

      # find lines matching the pattern, then substitute
      current.map do |line|
        new_line = line =~ match_pattern ? line.gsub(sub_pattern, substitute_str) : line
        raise ArgumentError, "Warning - The line with contents #{line} will match #{match_pattern} and #{sub_pattern} each chef run" if new_line =~ match_pattern && new_line =~ sub_pattern && @options[:safe]
        new_line
      end
    end
  end
end
