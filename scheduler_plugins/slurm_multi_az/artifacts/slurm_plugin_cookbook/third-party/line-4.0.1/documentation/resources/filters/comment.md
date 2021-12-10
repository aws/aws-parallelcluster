# Examples for the comment filter

## Original file

```text
line1
line2
line
```

## Output file

```text
#      line1
#      line2
line
```

## Filter

```ruby
addlines = "add1\nadd2\n"
filter_lines '/example/comment' do
 filters(comment: [/^line\d+$/, '#'/, '      ')
end
