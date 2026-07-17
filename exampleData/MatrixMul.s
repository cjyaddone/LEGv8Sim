// ========================================================================================
// This is the data loading and runInference code. DO NOT MODIFY. 
// You can edit or run your own test cases by modifying the .txt data files
// ========================================================================================
// Load the initialized input matrices
LDA     X0, a
LDA     X1, b
LDA     X2, c
LDA     X3, stride
LDA     X4, base

LDUR    X5, [X3, #0] // load stride
ADD     X3, X5, XZR  // Set n = stride
LDUR    X4, [X4, #0] // load base 

runInference:
        // Input:
        //  X0: The address of (pointer to) the first value of matirx A.
        //  X1: The address of (pointer to) the first value of matirx B.
        //  X2: The address of (pointer to) the first value of matirx C.
        //  X3: The current matrix size needed (n)
        //  X4: The base
        //  X5: The stride of the matrices

        BL     recBlockMul

        // Print trace
        ADDI   X1, XZR, #10      // X1 = newline character
        PUTCHAR X1
        ADD    X1, X0, XZR       // X1 = trace value returned in X0
        PUTINT X1
        ADDI   X1, XZR, #10      // newline
        PUTCHAR X1

        // Print result matrix C
        LDA    X0, c               // base address of result matrix
        LDA    X6, stride          // load stride's address
        LDUR    X1, [X6, #0]       // set n = stride
        LDUR    X2, [X6, #0]       // set stride
        
        BL     PRINTMATRIX

        STOP

// ========================================================================================





////////////////////////////////
//                            //
//       getAddr              //
//                            //
////////////////////////////////
getAddr:
        //  Input:
        //  X5: The address of (pointer to) the first value of the matirx.
        //  X6: The row of the element(0 indexed).
        //  X7: The column of the element(0 indexed).
        //  X8: The stride of the matirx(how many elements to skip to get to the next row).

        //   Output:
        //   X5: The address of (pointer to) the desired element of the matrix.

        //YOUR CODE STARTS HERE

        MUL    X9, X6, X8          // row * stride
        ADD    X9, X9, X7         // row * stride + col
        LSL    X9, X9, #3         // convert to byte offset (*8)
        ADD    X5, X5, X9         // base + offset

        BR     LR

        //YOUR CODE ENDS HERE





////////////////////////////////
//                            //
//       baseMultiplyAdd      //
//                            //
////////////////////////////////
baseMultiplyAdd:
        //  Input:
        //  X0: The address of (pointer to) the first value of matirx A.
        //  X1: The address of (pointer to) the first value of matirx B.
        //  X2: The address of (pointer to) the first value of matirx C.
        //  X3: n
        //  X4: The stride of the matrices
        //
        //  Output:
        //  X0: The trace of the resulting n*n block of C.

        //YOUR CODE STARTS HERE

        ADDI   X9, XZR, #0        // i = 0
        ADDI   X16, XZR, #0       // trace = 0

firstLoop:
        CMP    X9, X3
        B.GE   endFirstLoop

        ADDI   X10, XZR, #0       // j = 0

secondLoop:
        ADDI   X12, XZR, #0       // sum = 0
        CMP    X10, X3
        B.GE   endSecondLoop


        ADDI   X11, XZR, #0       // k = 0

thirdLoop:
        CMP    X11, X3
        B.GE   endThirdLoop

        // get A[i,k]'s address
        MUL    X13, X9, X4        // row * stride
        ADD    X13, X13, X11      // row * stride + col
        LSL    X13, X13, #3       // convert to byte offset (*8)
        ADD    X13, X13, X0       // Address of A[i,k]

        // get B[k,j]'s address
        MUL    X14, X11, X4       // row * stride
        ADD    X14, X14, X10      // row * stride + col
        LSL    X14, X14, #3       // convert to byte offset (*8)
        ADD    X14, X14, X1       // Address of B[k,j]

        LDUR   X13, [X13, #0]
        LDUR   X14, [X14, #0]

        MUL    X15, X13, X14      // A[i,k] * B[k,j]
        ADD    X12, X12, X15      // sum += A[i,k] * B[k,j]

        ADDI   X11, X11, #1       // k++
        B      thirdLoop

endThirdLoop:
        // get C[i,j]'s address
        MUL    X13, X9, X4        // row * stride
        ADD    X13, X13, X10      // row * stride + col
        LSL    X13, X13, #3       // convert to byte offset (*8)
        ADD    X13, X13, X2       // Address of C[i,j]

        LDUR   X14, [X13, #0]
        ADD    X14, X14, X12
        STUR   X14, [X13, #0]

        ADDI   X10, X10, #1       // j++
        B      secondLoop

endSecondLoop:
        // trace += C[i,i]
        MUL    X13, X9, X4        // row * stride
        ADD    X13, X13, X9       // row * stride + col (= i*stride + i)
        LSL    X13, X13, #3       // convert to byte offset (*8)
        ADD    X13, X13, X2       // Address of C[i,i]
        LDUR   X14, [X13, #0]
        ADD    X16, X16, X14      // trace += C[i,i]

        ADDI   X9, X9, #1         // i++
        B      firstLoop

endFirstLoop:
        ADD    X0, X16, XZR       // move trace to X0 for return

        BR     LR

        //YOUR CODE ENDS HERE





////////////////////////////////
//                            //
//       splitOffset          //
//                            //
////////////////////////////////
splitOffset:
        //  Input:
        //  X0: The address of (pointer to) the first value of the matirx.
        //  X1: n
        //  X2: 0-3 corresponding to the four quadrant of the matrix.
        //  X3: stride

        //   Output:
        //   X8: The address of (pointer to) the desired submatrix.


        //YOUR CODE STARTS HERE

        LSR    X9, X1, #1         // half = n / 2

firstIf:
        CBNZ   X2, secondIf       // if quadrant == 0, return base
        ADD    X8, X0, XZR        // return base in X8
        BR     LR

secondIf:
        ADDI   X10, XZR, #1
        SUBS   X10, X2, X10
        CBNZ   X10, thirdIf      // if quadrant != 1, try quadrant 2

        // Quadrant 1: top-right -> base + half
        ADDI   X10, XZR, #8
        MUL    X10, X9, X10       // half * 8
        ADD    X8, X0, X10        // return base + half*8
        BR     LR

thirdIf:
        ADDI   X10, XZR, #2
        SUBS   X10, X2, X10
        CBNZ   X10, else         // if quadrant != 2, try quadrant 3

        // Quadrant 2: bottom-left -> base + half * stride
        ADDI   X10, XZR, #8
        MUL    X9, X9, X3         // half * stride
        MUL    X10, X9, X10       // half * stride * 8
        ADD    X8, X0, X10        // return base + half*stride*8
        BR     LR

else:
        // Quadrant 3: bottom-right -> base + half * stride + half
        ADDI   X10, XZR, #8
        ADDI   X11, XZR, #1
        ADD    X11, X3, X11       // stride + 1 (avoid clobbering X3)
        MUL    X9, X9, X11        // half * (stride + 1)
        MUL    X10, X9, X10       // half * (stride + 1) * 8
        ADD    X8, X0, X10        // return base + half*(stride+1)*8
        BR     LR

        //YOUR CODE ENDS HERE




////////////////////////////////
//                            //
//       recBlockMul          //
//                            //
////////////////////////////////
recBlockMul:
        //  Input:
        //  X0: address of matrix A
        //  X1: address of matrix B
        //  X2: address of matrix C
        //  X3: current n
        //  X4: base
        //  X5: stride
        //
        //  Output:
        //  X0: sum of traces of all diagonal base-case blocks

        //YOUR CODE STARTS HERE

        SUBI   SP, SP, #128
        STUR   FP, [SP, #0]
        STUR   LR, [SP, #8]

        STUR   X19, [SP, #16]
        STUR   X20, [SP, #24]
        STUR   X21, [SP, #32]
        STUR   X22, [SP, #40]
        STUR   X23, [SP, #48]
        STUR   X24, [SP, #56]
        STUR   X25, [SP, #64]
        STUR   X16, [SP, #72]

        ADDI   FP, SP, #8

        ADD    X19, X0, XZR       // A
        ADD    X20, X1, XZR       // B
        ADD    X21, X2, XZR       // C
        ADD    X22, X3, XZR       // n
        ADD    X23, X4, XZR       // base
        ADD    X24, X5, XZR       // stride
        LSR    X25, X22, #1       // h = n / 2
        ADDI   X16, XZR, #0       // t = 0 (trace accumulator)

        SUBS   XZR, X22, X23
        B.LE   recBlockMul_base

        // --------------------------------------------------
        // C11 = A11*B11 (quadrant 0)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #0
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A11

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #0
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B11

        ADD    X0, X21, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #0
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #96]      // C11

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // compute, trace discarded (off-diagonal)

        // C11 += A12*B21 (quadrant 1 of A, quadrant 2 of B, same C11)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #1
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A12

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #2
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B21

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // trace is added to total
        ADD    X16, XZR, X0       // t += trace from diagonal block C11

        // --------------------------------------------------
        // C12 = A11*B12 (quadrant 0 of A, quadrant 1 of B)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #0
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A11

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #1
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B12

        ADD    X0, X21, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #1
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #96]      // C12

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // off-diagonal, trace discarded

        // C12 += A12*B22 (quadrant 1 of A, quadrant 3 of B, same C12)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #1
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A12

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #3
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B22

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // off-diagonal, trace discarded

        // --------------------------------------------------
        // C21 = A21*B11 (quadrant 2 of A, quadrant 0 of B)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #2
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A21

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #0
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B11

        ADD    X0, X21, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #2
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #96]      // C21

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // off-diagonal, trace discarded

        // C21 += A22*B21 (quadrant 3 of A, quadrant 2 of B, same C21)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #3
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A22

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #2
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B21

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // off-diagonal, trace discarded

        // --------------------------------------------------
        // C22 = A21*B12 (quadrant 2 of A, quadrant 1 of B)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #2
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A21

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #1
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B12

        ADD    X0, X21, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #3
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #96]      // C22

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // off-diagonal, trace discarded

        // C22 += A22*B22 (quadrant 3 of A and B, same C22 - DIAGONAL)
        ADD    X0, X19, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #3
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #80]      // A22

        ADD    X0, X20, XZR
        ADD    X1, X22, XZR
        ADDI   X2, XZR, #3
        ADD    X3, X24, XZR
        BL     splitOffset
        STUR   X8, [SP, #88]      // B22

        LDUR   X0, [SP, #80]
        LDUR   X1, [SP, #88]
        LDUR   X2, [SP, #96]
        ADD    X3, X25, XZR
        ADD    X4, X23, XZR
        ADD    X5, X24, XZR
        BL     recBlockMul        // trace is added to total
        ADD    X16, X16, X0       // t += trace from diagonal block C22

        B      recBlockMul_done

recBlockMul_base:
        ADD    X0, X19, XZR
        ADD    X1, X20, XZR
        ADD    X2, X21, XZR
        ADD    X3, X22, XZR
        ADD    X4, X24, XZR
        BL     baseMultiplyAdd
        ADD    X16, XZR, X0       // move trace to X16 for accumulator

recBlockMul_done:
        ADD    X0, X16, XZR       // move accumulated trace to X0 for return
        LDUR   X25, [SP, #64]
        LDUR   X24, [SP, #56]
        LDUR   X23, [SP, #48]
        LDUR   X22, [SP, #40]
        LDUR   X21, [SP, #32]
        LDUR   X20, [SP, #24]
        LDUR   X19, [SP, #16]
        LDUR   X16, [SP, #72]
        LDUR   LR, [SP, #8]
        LDUR   FP, [SP, #0]
        ADDI   SP, SP, #128
        BR     LR

//YOUR CODE ENDS HERE






// ========================================================================================
// Functions after this are for printing results. DO NOT MODIFY
// ========================================================================================
PRINTMATRIX:
        // Input:
        // X0: base address of matrix
        // X1: n (matrix dimension)
        // X2: stride

        SUBI   SP, SP, #40
        STUR   FP, [SP, #0]
        ADDI   FP, SP, #8
        STUR   LR, [SP, #8]

        // Save parameters
        STUR   X0, [SP, #16]     // save base
        STUR   X1, [SP, #24]     // save n
        STUR   X2, [SP, #32]     // save stride

        ADDI   X5, XZR, #32      // X5 = space character
        ADDI   X6, XZR, #10      // X6 = newline character
        ADDI   X3, XZR, #0       // i = 0 (row counter)

ROW_LOOP:
        LDUR   X1, [SP, #24]     // load n
        CMP    X3, X1            // if i >= n, done
        B.GE   PRINT_DONE

        ADDI   X4, XZR, #0       // j = 0 (col counter)

COL_LOOP:
        LDUR   X1, [SP, #24]     // load n
        CMP    X4, X1            // if j >= n, end row
        B.GE   END_ROW

        // Calculate address: base + (i * stride + j) * 8
        LDUR   X7, [SP, #16]     // load base
        MUL    X19, X3, X2       // i * stride
        ADD    X19, X19, X4      // i * stride + j
        LSL    X19, X19, #3      // * 8 for byte offset
        ADD    X7, X7, X19       // final address

        // Load and print value
        LDUR   X1, [X7, #0]      // load matrix[i][j]
        PUTINT X1

        // Print space
        PUTCHAR X5

        // j++
        ADDI   X4, X4, #1
        B      COL_LOOP

END_ROW:
        // Print newline
        PUTCHAR X6

        // i++
        ADDI   X3, X3, #1
        B      ROW_LOOP

PRINT_DONE:
        LDUR   LR, [SP, #8]
        LDUR   FP, [SP, #0]
        ADDI   SP, SP, #40
        BR     LR