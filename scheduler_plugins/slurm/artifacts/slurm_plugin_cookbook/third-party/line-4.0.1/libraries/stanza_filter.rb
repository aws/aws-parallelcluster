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

# Filter insert or change keys in files formatted as stanzas
module Line
  class Filter
    def stanza(current, args)
      # Assumes stanzas are named uniquely across the file and contiguous
      # Stanza starts with ^[<name>]$
      # Stanza ends with next stanza or EOF
      # Sets one instance of a key in a stanza to a new value
      # Only the last matching stanza will be updated in case of duplicated stanza names
      # Only the last matching key value within a stanza will be updated in case of duplicated key names
      # Supported stanza styles are equal "keyword = value" and value "keyword value".
      # Example
      # [a1]
      #   att1 = value1
      #   lines in the a1 stanza
      # [a2]
      #   att2 = value2

      # args[0] stanza to select, name of the stanza to match if not there it will be created
      # args[1] {keys, values} to replace or add to the stanza
      # args[2] keyword style option
      # Comment lines will be ignored
      #
      @stanza_name = verify_kind(args[0], String)
      @settings = verify_kind(args[1], Hash) # A hash of keywords and values
      @key_style = (verify_one_of(args[2], [nil, :equal, 'equal', :value, 'value']) || :equal).to_sym

      verify_stanza_name
      verify_keys

      stanza_names = find_stanzas(current)
      add_stanza(current, stanza_names, @stanza_name) unless stanza_names[@stanza_name]
      stanza_settings = parse_stanza(current, stanza_names, @stanza_name)
      new_settings = diff_settings(stanza_settings, @settings)
      current = update_stanza(current, stanza_names, @stanza_name, new_settings)
      expand(current)
    end

    def find_stanzas(current)
      stanza_names = {}
      current.each_index do |i|
        md = stanza_pattern.match(current[i])
        next unless md
        stanza_names[md[:name]] = i
      end
      stanza_names
    end

    def add_stanza(current, stanza_names, stanza_name)
      current << "[#{stanza_name}]"
      stanza_names[stanza_name] = current.size - 1
    end

    def parse_stanza(current, stanza_names, stanza_name)
      settings = {}
      si = stanza_names[stanza_name] + 1
      while si < current.size && current[si] !~ stanza_pattern
        md = key_regex.match(current[si])
        settings[md[:key].to_sym] = { value: md[:value], location: si } if md
        si += 1
      end
      settings
    end

    def diff_settings(stanza_settings, settings)
      diff_values = {}
      settings.each do |s_key, s_value|
        value = s_value unless stanza_settings[s_key.to_sym] && stanza_settings[s_key.to_sym][:value] == s_key
        location = stanza_settings[s_key.to_sym] ? stanza_settings[s_key.to_sym][:location] : nil
        diff_values[s_key.to_sym] = { value: value, location: location }
      end
      diff_values
    end

    def update_stanza(current, stanza_names, stanza_name, settings)
      settings.each do |keyname, attrs|
        if attrs[:location].nil?
          if current[stanza_names[stanza_name]].class == Line::Replacement
            current[stanza_names[stanza_name]].add(rep_value(keyname, attrs[:value]), :after)
          else
            current[stanza_names[stanza_name]] = Replacement.new(current[stanza_names[stanza_name]], rep_value(keyname, attrs[:value]), :after)
          end
        else
          current[attrs[:location]] = Replacement.new(current[attrs[:location]], rep_value(keyname, attrs[:value]), :replace)
        end
      end
      current
    end

    def rep_value(key, value)
      ["  #{key}#{key_seperator}#{value}"]
    end

    def key_regex
      /\s*(?<key>#{name_pattern})\s*#{key_seperator}\s*(?<value>.*)\s*/
    end

    def key_value_regex
      /(?<key>#{name_pattern})/
    end

    def key_seperator
      @key_style == :equal ? ' = ' : ' '
    end

    def name_pattern
      '[\w.\-_%@]*'
    end

    def stanza_pattern
      /^\[(?<name>#{name_pattern})\]\s*/ # deal with comments on stanza line
    end

    def verify_keys
      # unless the key names match the pattern the stanza will be inserted during each converge
      @settings.each_key do |key|
        raise ArgumentError, "Invalid key value #{key}" unless key =~ key_value_regex
      end
    end

    def verify_stanza_name
      # unless the new stanza name matches the pattern the stanza will be inserted during each converge
      raise ArgumentError, "Invalid stanza name #{@stanza_name}, should match #{stanza_regex}" unless @stanza_name =~ key_value_regex
    end
  end
end
