#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {

    double *array;
    long int num_elem, i, total_mem;

    if (argc > 2) {
        printf("Only one argument (memory size) is supported\n");
        exit(1);
    }

    if (argc==2) {
        total_mem = atol(argv[1]);
    }
    else {
        total_mem = 1e8;
    }

    printf("Memory to be allocated: %ld\n", total_mem);

    array = (double*) malloc(total_mem);
    num_elem = total_mem / (long int) sizeof(double);

    for (i = 0; i < num_elem; i++) {
        array[i] = 1.0;
    }
    sleep(30);

    if (array == NULL) {
        printf("Memory not allocated.\n");
        return 1;
    }
    else {
        printf("Memory successfully allocated.\n");
        free(array);
        printf("Memory successfully freed.\n");
    }

    return 0;
}
