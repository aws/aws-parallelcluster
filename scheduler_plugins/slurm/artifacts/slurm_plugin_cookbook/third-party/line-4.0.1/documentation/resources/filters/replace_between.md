# Examples for the replace_between filter

## Example 1: Original file

```text
line1
line2
line3
```

## Example 1: Output file

```textruby
line1
rep1
rep2
line3
```

## Example 1: Filter

```ruby
replines = "rep1\nrep2\n"
filter_lines '/example/replace_between' do
 filters(replace_between: [/^line1$/, /^line3$/, replines])
end
```

## Example 2: Original file

```text
line1
line2
line3
```

## Example 2: Output file

```texttext
rep1
rep2
```

## Example 2: Filter

```rubyruby
replines = "rep1\nrep2\n"
filter_lines '/example/replace_between_include_bounds' do
 filters(replace_between: [/^line1$/, /^line3$/, replines, :include])
end
```

## Example 3: Original file

```text
line1
line2
line3
```

## Example 3: Output file

```texttext
rep1
rep2
line3
```

## Example 3: Filter

```rubyruby
replines = "rep1\nrep2\n"
filter_lines '/example/replace_between_include_first_boundary' do
 filters(replace_between: [/^line1$/, /^line3$/, replines, :first])
end
```

## Example 4: Replace a set of lines delimted by a semicolon

## Example 4: Original file

```text
line1 = text
line2;
line3;
```

## Example 4: Output file

```texttext
line1 = rep1
rep2;
line3
```

## Example 4: Filter

```rubyruby
replines = "line1 = rep1\nrep2;\n"
filter_lines '/example/replace_between_using_next' do
 filters(replace_between: [/^line1/, /;$/, replines, [:include,:next])
end
```
