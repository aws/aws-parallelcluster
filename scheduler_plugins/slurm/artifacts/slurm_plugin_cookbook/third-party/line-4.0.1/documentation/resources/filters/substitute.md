# Examples for the substitute filter

## Original file

```text
line1 text here
line2 text here
```

## Output file

```texttext
line1 text here
line2 text new
```

## Filter

```ruby
filter_lines '/example/substitute' do
 filters(substitute: [/^line2/, /here/, 'new'])
end
```
