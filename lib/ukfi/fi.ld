SECTIONS
{
	.uk_fitab ALIGN(8) : {
		uk_fitab_start = .;
		KEEP(*(.uk_fitab))
		uk_fitab_end = .;
	}
}
INSERT AFTER .data;
