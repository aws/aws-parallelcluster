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

# Filter to comment lines that  match
module Line
  class Filter
    def comment(current, args)
      # current is an array of lines
      # args[0] is a pattern to match a line
      # args[1] Comment string
      # args[2] Space between comment string and the real line
      #
      # returns array with inserted lines
      match_pattern = verify_kind(args[0], Regexp)
      @comment_str = verify_kind(args[1], [String, NilClass]) || '#'
      @comment_space = verify_kind(args[2], [String, NilClass]) || ' '

      # find lines matching the pattern
      current.each_index do |i|
        if current[i] =~ match_pattern
          next if commented?(current[i])
          current[i] = mark_as_comment(current[i])
        end
      end
      current
    end

    def commented?(line)
      line =~ /^\s*#{@comment_str}/
    end

    def mark_as_comment(line)
      "#{@comment_str}#{@comment_space}#{line}"
    end
  end
end
