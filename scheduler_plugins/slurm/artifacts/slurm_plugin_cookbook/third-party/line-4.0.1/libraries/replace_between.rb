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

# Filter to replace lines between two matches
module Line
  class Filter
    def replace_between(current, args)
      # replace the lines matching a pattern found between lines matching two patterns
      # current is an array of lines
      # args[0] is a pattern. Replace lines after this pattern
      # args[1] is a pattern. Replace lines before this pattern
      # args[2] is a string or an array of lines to insert
      # args[3] is a symbol or an array of symbols. Include the start and end lines in the replace match. Default is :exclude. Other options are :first, :include, :last, :next
      # args[4] options.
      #
      # returns array with replaced lines
      start_pattern = verify_kind(args[0], Regexp)
      end_pattern = verify_kind(args[1], Regexp)
      insert_array = prepare_insert_lines(args[2])
      ends = verify_all_of(args[3], [nil, :exclude, :first, :include, :last, :next]) || :exclude
      options(args[4], safe: [true, false])

      # The start and end patterns shouldn't match lines inside the insert array unless the bounds match too.
      # if the patterns match an internal replacement line replacing may add lines every time.
      unless match_insert_lines?(start_pattern, insert_array[0..0], @options[:safe]) && match_limits(ends, [:first, :include])
        verify_insert_lines(start_pattern, insert_array[1..-1], @options[:safe])
      end
      unless match_insert_lines?(end_pattern, insert_array[-1..-1], @options[:safe]) && match_limits(ends, [:last, :include])
        verify_insert_lines(end_pattern, insert_array[0...-1], @options[:safe])
      end

      first_matches = []
      second_matches = []
      current.each_index do |i|
        first_matches << i if current[i] =~ start_pattern
        second_matches << i if current[i] =~ end_pattern
      end

      start_line = first_matches.first
      end_line = match_limits(ends, [:next]) ? next_match_after(start_line, second_matches) : second_matches.last
      puts
      puts "START #{start_line}"
      puts "END #{end_line}"
      puts "ENDS #{ends}"
      puts "Current #{current}"
      puts "Start Pattern #{start_pattern}"
      puts "END Pattern #{end_pattern}"
      puts "SMATCH #{second_matches}"

      if start_line && end_line && start_line <= end_line
        replace_start = match_limits(ends, [:first, :include]) ? start_line : start_line + 1
        replace_end = match_limits(ends, [:last, :include]) ? end_line : end_line - 1
        (replace_start..replace_end).each do |i|
          current[i] = Replacement.new(current[i], '', :delete)
        end
        current[replace_start] = Replacement.new(current[replace_start], insert_array, :replace)
      end
      puts "NEW #{expand(current)}"
      expand(current)
    end
  end
end
